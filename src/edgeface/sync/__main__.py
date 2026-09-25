"""The sync process.

    python3 -m edgeface.sync --config configs/nano.yaml
    python3 -m edgeface.sync --config configs/dev.yaml --once      # one cycle, for testing

Configuration that must not live in git (server URL, device token) comes from the
environment, typically /etc/edgeface/sync.env loaded by systemd:

    EDGEFACE_SERVER=https://server.local:8443
    EDGEFACE_DEVICE_ID=kiosk-01
    EDGEFACE_TOKEN=...
    EDGEFACE_CA=/etc/edgeface/server_ca.pem
"""
import argparse
import os
import signal
import sys
import time

from edgeface import config as cfg_mod
from edgeface.common.log import get_logger
from edgeface.engine.models import load_manifest
from edgeface.storage import clock, db, outbox
from edgeface.storage.db import get_meta, set_meta, transaction
from edgeface.sync import puller, uploader
from edgeface.sync.bundle import BundleError, sync_bundle
from edgeface.sync.client import ServerClient, ServerError

LOG = get_logger("sync")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _abs_path(path):
    return path if os.path.isabs(path) else os.path.join(REPO, path)


def client_from_env(cfg):
    base_url = os.environ.get("EDGEFACE_SERVER") or (cfg.get("sync") or {}).get("server_url")
    if not base_url:
        raise SystemExit("set EDGEFACE_SERVER (or sync.server_url) to the server URL")
    ca = os.environ.get("EDGEFACE_CA")
    return ServerClient(base_url=base_url,
                        token=os.environ.get("EDGEFACE_TOKEN", ""),
                        device_id=os.environ.get("EDGEFACE_DEVICE_ID", "kiosk-01"),
                        verify=ca if ca else True)


class SyncService(object):
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.sync_cfg = cfg.get("sync") or {}
        self.conn = db.open_db(_abs_path(cfg["storage"]["db_path"]))
        self.client = client or client_from_env(cfg)
        manifest = load_manifest()
        recognizer = cfg["models"]["recognizer"]
        self.recognizer_sha256 = (manifest.get(recognizer) or {}).get("sha256")
        self.bundles_dir = _abs_path(self.sync_cfg.get("bundles_dir", "var/bundles"))
        self.key_path = self.sync_cfg.get("bundle_key_path", "/etc/edgeface/bundle.key")
        self.running = False
        self.last_pull = 0.0
        self.last_heartbeat = 0.0
        self.last_bundle_check = 0.0

    def upload(self, now=None):
        return uploader.drain(self.conn, self.client,
                              batch_size=self.sync_cfg.get("batch_size", 50),
                              now=now, backoff=self.sync_cfg.get("backoff"))

    def pull(self, now=None):
        return puller.pull_once(self.conn, self.client, self.recognizer_sha256, now,
                                ttl_hours=self.cfg["retention"]["patients_hours"])

    def heartbeat(self, now=None):
        from edgeface.storage import templates

        try:
            return self.client.heartbeat(
                gallery_version=templates.gallery_version(self.conn),
                outbox_pending=outbox.pending_count(self.conn),
                model_version=self.sync_cfg.get("model_version"))
        except ServerError as exc:
            LOG.warning("heartbeat failed: %s", exc)
            return None

    def bundles(self, now=None):
        try:
            return sync_bundle(self.conn, self.client, self.bundles_dir, self.key_path, now)
        except (BundleError, ServerError) as exc:
            LOG.warning("bundle sync skipped: %s", exc)
            return {"changed": False, "reason": str(exc)}

    SYNC_REQUEST_KEY = "sync_requested_at"

    def requested(self):
        """True when a nurse asked for a pull from the kiosk's status screen.

        Cleared as soon as it is seen, so the request means "once, now" rather than
        "from now on".
        """
        value = get_meta(self.conn, self.SYNC_REQUEST_KEY)
        try:
            asked = float(value or 0)
        except (TypeError, ValueError):
            asked = 0.0
        if asked <= 0:
            return False
        with transaction(self.conn):
            set_meta(self.conn, self.SYNC_REQUEST_KEY, 0)
        LOG.info("pulling now: asked for from the kiosk")
        return True

    def cycle(self, now=None):
        """One pass: upload, then pull when due, then heartbeat and bundles."""
        now = clock.now() if now is None else now
        result = {"upload": self.upload(now)}
        due = (now - self.last_pull) >= self.sync_cfg.get("pull_interval_s", 300)
        if due or self.requested():
            try:
                result["pull"] = self.pull(now)
                self.last_pull = now
            except ServerError as exc:
                LOG.warning("pull failed: %s", exc)
                result["pull"] = {"error": str(exc)}
        if (now - self.last_heartbeat) >= self.sync_cfg.get("heartbeat_interval_s", 300):
            result["heartbeat"] = self.heartbeat(now)
            self.last_heartbeat = now
        if (now - self.last_bundle_check) >= self.sync_cfg.get("bundle_interval_s", 3600):
            result["bundle"] = self.bundles(now)
            self.last_bundle_check = now
        return result

    def run(self):
        self.running = True
        interval = self.sync_cfg.get("upload_interval_s", 30)
        LOG.info("sync started (upload every %ss, pull every %ss)",
                 interval, self.sync_cfg.get("pull_interval_s", 300))
        while self.running:
            try:
                self.cycle()
            except Exception as exc:          # noqa: BLE001 - the loop must never die
                LOG.exception("sync cycle failed: %s", exc)
            for _ in range(int(interval * 10)):
                if not self.running:
                    break
                time.sleep(0.1)
        self.close()

    def stop(self, *_args):
        LOG.info("stopping")
        self.running = False

    def close(self):
        self.client.close()
        self.conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    ap.add_argument("--once", action="store_true", help="run a single cycle and exit")
    args = ap.parse_args(argv)

    cfg = cfg_mod.load_config(args.config)
    service = SyncService(cfg)
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    if args.once:
        # Force every periodic task to run in this single cycle.
        service.last_pull = service.last_heartbeat = service.last_bundle_check = -1e9
        result = service.cycle()
        LOG.info("cycle: %s", result)
        service.close()
        return 0
    service.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
