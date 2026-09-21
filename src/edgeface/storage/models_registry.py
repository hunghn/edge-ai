"""Model bundles pulled by the sync process.

The engine loads whatever is 'active'. A bundle only becomes active when its SHA-256
and signature verified (M7), and the swap happens on an engine restart, never live.
"""
from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

STAGED = "staged"
ACTIVE = "active"
REJECTED = "rejected"


def register(conn, version, sha256, path, status=STAGED, at=None):
    at = clock.now() if at is None else at
    cur = conn.execute(
        "UPDATE model_bundles SET sha256 = ?, path = ?, status = ?, installed_at = ? "
        "WHERE version = ?", (sha256, path, status, at, version))
    if cur.rowcount == 0:
        conn.execute("INSERT INTO model_bundles (version, sha256, path, status, installed_at) "
                     "VALUES (?, ?, ?, ?, ?)", (version, sha256, path, status, at))
        return "inserted"
    return "updated"


def set_status(conn, version, status):
    if status not in (STAGED, ACTIVE, REJECTED):
        raise ValueError("unknown bundle status: {}".format(status))
    if status == ACTIVE:
        # Exactly one active bundle at a time.
        conn.execute("UPDATE model_bundles SET status = ? WHERE status = ?", (STAGED, ACTIVE))
    return conn.execute("UPDATE model_bundles SET status = ? WHERE version = ?",
                        (status, version)).rowcount


def active(conn):
    return read_one(conn, "SELECT * FROM model_bundles WHERE status = ?", (ACTIVE,))


def get(conn, version):
    return read_one(conn, "SELECT * FROM model_bundles WHERE version = ?", (version,))


def list_all(conn):
    return read_all(conn, "SELECT * FROM model_bundles ORDER BY installed_at DESC")
