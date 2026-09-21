"""Local data retention: the privacy guarantee of the kiosk.

Run periodically by the engine between sessions (retention.interval_s). It:
  - deletes patients past their 24 h TTL (C-04), taking templates and appointments with
    them through ON DELETE CASCADE;
  - deletes every patient on the revocation list pulled from the server;
  - deletes expired spoof evidence files (C-16) and orphan files;
  - deletes session logs and latency samples past their TTL (C-17);
  - deletes acknowledged outbox events; unsent ones are kept whatever happens;
  - truncates the WAL.

Clock guard: TTLs are wall-clock based, and a Jetson Nano without network can boot with
a wrong clock. If the clock jumps backwards, or forwards by more than
`max_forward_jump_s`, the run is skipped so a bad clock cannot wipe the gallery.
"""
from edgeface.common.log import get_logger
from edgeface.storage import clock, evidence, metrics, outbox, patients, sessions
from edgeface.storage.db import checkpoint, get_meta, set_meta, transaction
from edgeface.storage.templates import bump_gallery_version

LOG = get_logger("retention")

_LAST_RUN_KEY = "retention_last_run"
DEFAULT_MAX_FORWARD_JUMP_S = 7 * 86400.0
SENT_EVENT_TTL_S = 86400.0


def check_clock(conn, now, max_forward_jump_s=DEFAULT_MAX_FORWARD_JUMP_S):
    """(ok, reason, last_run). Refuses to delete anything when the clock looks wrong."""
    raw = get_meta(conn, _LAST_RUN_KEY)
    if raw is None:
        return True, "first_run", None
    last_run = float(raw)
    if now < last_run - 60.0:
        return False, "clock_went_backwards", last_run
    if now - last_run > max_forward_jump_s:
        return False, "clock_jumped_forward", last_run
    return True, "ok", last_run


def run_once(conn, cfg=None, now=None, evidence_dir=None,
             max_forward_jump_s=DEFAULT_MAX_FORWARD_JUMP_S, force=False):
    """Delete everything that is past its retention. Returns a dict of counts."""
    cfg = cfg or {}
    now = clock.now() if now is None else now
    retention = cfg.get("retention", {}) if hasattr(cfg, "get") else {}
    sessions_days = retention.get("sessions_days", 30)
    metrics_days = retention.get("metrics_days", 30)

    ok, reason, last_run = check_clock(conn, now, max_forward_jump_s)
    if not ok and not force:
        LOG.warning("retention skipped: %s (last run %s, now %s)", reason, last_run, now)
        return {"skipped": reason}

    result = {"skipped": None}
    with transaction(conn):
        result["patients_expired"] = patients.delete_expired(conn, now)
        result["patients_revoked"] = patients.apply_revocations(conn, now)
        result["sessions"] = sessions.purge_expired(conn, now)
        result["metrics"] = metrics.purge_older_than(conn, now - metrics_days * 86400.0)
        result["outbox_sent"] = outbox.purge_sent(conn, now - SENT_EVENT_TTL_S)
        if result["patients_expired"] or result["patients_revoked"]:
            # The gallery changed, so the engine must reload it before the next session.
            result["gallery_version"] = bump_gallery_version(conn)
        set_meta(conn, _LAST_RUN_KEY, now)

    # Files are deleted outside the write transaction, but rows go in their own one.
    if evidence_dir is not None:
        with transaction(conn):
            files, rows = evidence.purge_expired(conn, now)
        result["evidence_files"] = files
        result["evidence_rows"] = rows
        result["evidence_orphans"] = evidence.purge_orphans(conn, evidence_dir)

    checkpoint(conn)
    LOG.info("retention: %s", result)
    return result


def due(conn, now=None, interval_s=600.0):
    """True when the last run is older than interval_s (or never ran)."""
    now = clock.now() if now is None else now
    raw = get_meta(conn, _LAST_RUN_KEY)
    if raw is None:
        return True
    return (now - float(raw)) >= interval_s
