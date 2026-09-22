"""Model bundles: download, verify, stage. Never swap a model under a running engine.

Verification is deliberately paranoid. A model file is executable logic in disguise: a
tampered detector could be made to see a face where there is none. So the archive's
SHA-256 must match the server's claim, the HMAC signature must match the shared key
(D-24), every file inside must match the manifest, and only then is the bundle staged
for the engine to pick up on its next restart.
"""
import hashlib
import hmac
import os
import shutil
import tarfile

from edgeface.common.log import get_logger
from edgeface.storage import clock, models_registry
from edgeface.storage.db import transaction

LOG = get_logger("sync.bundle")

MANIFEST_NAME = "manifest.yaml"


class BundleError(Exception):
    pass


def sha256_file(path, chunk=1 << 20):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_signature(sha256_hex, version, key):
    message = "{}|{}".format(sha256_hex, version).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def read_key(path):
    with open(path, "rb") as f:
        return f.read().strip()


def verify_archive(path, version, sha256_hex, signature, key):
    """Raises BundleError unless the file is exactly what the server signed."""
    actual = sha256_file(path)
    if actual != sha256_hex:
        raise BundleError("sha256 mismatch: got {} expected {}".format(actual[:16],
                                                                       sha256_hex[:16]))
    expected = expected_signature(sha256_hex, version, key)
    if not hmac.compare_digest(expected, signature or ""):
        raise BundleError("signature mismatch for bundle " + version)
    return True


def _safe_members(archive, destination):
    """Refuse absolute paths, '..' and symlinks: a bundle must not write outside its dir."""
    destination = os.path.abspath(destination)
    for member in archive.getmembers():
        if member.issym() or member.islnk():
            raise BundleError("bundle contains a link: " + member.name)
        target = os.path.abspath(os.path.join(destination, member.name))
        if not target.startswith(destination + os.sep) and target != destination:
            raise BundleError("bundle escapes its directory: " + member.name)
        yield member


def extract(path, destination):
    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination)
    with tarfile.open(path, "r:*") as archive:
        archive.extractall(destination, members=_safe_members(archive, destination))
    return destination


def verify_contents(directory):
    """Every file listed in the bundle's manifest must be present with the right hash."""
    import yaml

    manifest_path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.exists(manifest_path):
        raise BundleError("bundle has no " + MANIFEST_NAME)
    with open(manifest_path) as f:
        manifest = yaml.safe_load(f) or {}
    checked = 0
    for name, entry in manifest.items():
        if not isinstance(entry, dict) or not entry.get("file"):
            continue
        file_path = os.path.join(directory, entry["file"])
        if not os.path.exists(file_path):
            raise BundleError("{}: missing file {}".format(name, entry["file"]))
        expected = entry.get("sha256")
        if expected:
            actual = sha256_file(file_path)
            if actual != expected:
                raise BundleError("{}: sha256 mismatch ({} != {})".format(
                    name, actual[:16], expected[:16]))
            checked += 1
    if not checked:
        raise BundleError("manifest listed no verifiable files")
    return checked


def install(conn, client, meta, bundles_dir, key, now=None):
    """Download and stage one bundle. Returns a summary; raises BundleError on any doubt.

    Staged, not activated: the engine loads models at start-up only, so a swap happens
    when it restarts, never mid-session.
    """
    now = clock.now() if now is None else now
    version = meta["version"]
    if not os.path.isdir(bundles_dir):
        os.makedirs(bundles_dir)
    archive_path = os.path.join(bundles_dir, "{}.tar".format(version))
    tmp_path = archive_path + ".part"
    client.download(meta["url"], tmp_path)

    try:
        verify_archive(tmp_path, version, meta["sha256"], meta.get("signature"), key)
        os.rename(tmp_path, archive_path)
        staged_dir = os.path.join(bundles_dir, version)
        extract(archive_path, staged_dir)
        files = verify_contents(staged_dir)
    except BundleError as exc:
        for path in (tmp_path, archive_path):
            if os.path.exists(path):
                os.remove(path)
        with transaction(conn):
            models_registry.register(conn, version, meta.get("sha256", ""), "",
                                     models_registry.REJECTED, now)
        LOG.error("bundle %s rejected: %s", version, exc)
        raise

    with transaction(conn):
        models_registry.register(conn, version, meta["sha256"], staged_dir,
                                 models_registry.STAGED, now)
    LOG.info("bundle %s staged at %s (%d files verified)", version, staged_dir, files)
    return {"version": version, "path": staged_dir, "files": files, "status": "staged"}


def sync_bundle(conn, client, bundles_dir, key_path, now=None):
    """Check the server for a newer bundle; do nothing when already up to date."""
    meta = client.get_latest_bundle()
    if not meta:
        return {"changed": False, "reason": "no bundle on server"}
    existing = models_registry.get(conn, meta["version"])
    if existing and existing["status"] in (models_registry.STAGED, models_registry.ACTIVE):
        return {"changed": False, "reason": "already have " + meta["version"]}
    if not os.path.exists(key_path):
        raise BundleError("no bundle key at {} — copy it from the server".format(key_path))
    return install(conn, client, meta, bundles_dir, read_key(key_path), now)
