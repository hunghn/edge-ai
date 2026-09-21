"""Spoof evidence images.

C-16: only the face crop is kept, as JPEG, with a 7-day TTL. This is the single
exception to "no face images on disk", so the retention job must actually delete both
the file and the row.
"""
import hashlib
import os
import uuid

from edgeface.storage import clock
from edgeface.storage.db import read_all


def save(conn, session_id, jpeg_bytes, directory, ttl_days=7, at=None, evidence_id=None):
    """Write the JPEG atomically (tmp + rename) and record it. Returns the row as a dict.

    Must be called inside db.transaction() so a crash cannot leave a row without a file;
    a file without a row is possible and is cleaned up by purge_orphans().
    """
    at = clock.now() if at is None else at
    evidence_id = evidence_id or uuid.uuid4().hex
    if not os.path.isdir(directory):
        os.makedirs(directory)
    path = os.path.join(directory, evidence_id + ".jpg")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(jpeg_bytes)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, path)
    digest = hashlib.sha256(jpeg_bytes).hexdigest()
    expires_at = at + ttl_days * 86400.0
    conn.execute(
        "INSERT INTO evidence (evidence_id, session_id, path, sha256, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", (evidence_id, session_id, path, digest, at, expires_at))
    return {"evidence_id": evidence_id, "session_id": session_id, "path": path,
            "sha256": digest, "created_at": at, "expires_at": expires_at}


def get_for_session(conn, session_id):
    return read_all(conn, "SELECT * FROM evidence WHERE session_id = ? ORDER BY created_at",
                    (session_id,))


def purge_expired(conn, now=None):
    """Delete expired files then their rows. Returns (files_deleted, rows_deleted)."""
    now = clock.now() if now is None else now
    rows = read_all(conn, "SELECT evidence_id, path FROM evidence WHERE expires_at <= ?", (now,))
    files = 0
    for row in rows:
        try:
            os.remove(row["path"])
            files += 1
        except OSError:
            pass  # already gone; the row still has to go
    deleted = conn.execute("DELETE FROM evidence WHERE expires_at <= ?", (now,)).rowcount
    return files, deleted


def purge_orphans(conn, directory):
    """Delete .jpg/.tmp files in `directory` that no row references (crash leftovers)."""
    if not os.path.isdir(directory):
        return 0
    known = set(row["path"] for row in read_all(conn, "SELECT path FROM evidence"))
    removed = 0
    for name in os.listdir(directory):
        if not (name.endswith(".jpg") or name.endswith(".tmp")):
            continue
        path = os.path.join(directory, name)
        if path not in known:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                pass
    return removed


def count(conn):
    return int(conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"])
