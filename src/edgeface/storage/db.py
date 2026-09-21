"""Connection setup and migrations.

Three processes share one database file, so every connection runs in WAL mode with a
busy timeout, and every write happens inside a short BEGIN IMMEDIATE transaction.

SQLite on Ubuntu 18.04 is 3.22: no UPSERT (3.24), no window functions (3.25), no
RETURNING (3.35). tests/unit/test_sql_compat.py guards against those creeping in.
"""
import contextlib
import os
import random
import re
import sqlite3
import time

from edgeface.storage import clock

SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema")
DEFAULT_TIMEOUT_S = 5.0
_MIGRATION_RE = re.compile(r"^(\d+)_.*\.sql$")


def connect(path, timeout_s=DEFAULT_TIMEOUT_S):
    """Open (and create) the database with the PRAGMAs every process needs.

    isolation_level=None turns off pysqlite's implicit transaction handling: we issue
    BEGIN IMMEDIATE ourselves in transaction().
    """
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    conn = sqlite3.connect(path, timeout=timeout_s, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=%d" % int(timeout_s * 1000))
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _is_locked(exc):
    message = str(exc).lower()
    return "locked" in message or "busy" in message


@contextlib.contextmanager
def transaction(conn, retries=5, base_delay_s=0.05):
    """Write transaction. Retries only while acquiring the write lock, never the body.

    Keep the body short: never run inference or network I/O inside it.
    """
    for attempt in range(retries + 1):
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as exc:
            if attempt >= retries or not _is_locked(exc):
                raise
            time.sleep(base_delay_s * (2 ** attempt) * (0.5 + random.random()))
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def read_all(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def read_one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def migration_files(schema_dir=SCHEMA_DIR):
    """[(version, path)] sorted by version."""
    out = []
    for name in sorted(os.listdir(schema_dir)):
        match = _MIGRATION_RE.match(name)
        if match:
            out.append((int(match.group(1)), os.path.join(schema_dir, name)))
    return sorted(out)


def schema_version(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    value = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"]
    return int(value or 0)


def migrate(conn, schema_dir=SCHEMA_DIR):
    """Apply pending migrations in order. Returns the list of versions applied.

    Each file runs through executescript, which commits implicitly, so a migration is
    not atomic with its version row. The version is written immediately afterwards, and
    every migration is written to be re-runnable (CREATE TABLE IF NOT EXISTS,
    INSERT OR IGNORE), so a crash in between leaves the database usable.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                 "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
    current = schema_version(conn)
    applied = []
    for version, path in migration_files(schema_dir):
        if version <= current:
            continue
        with open(path) as f:
            conn.executescript(f.read())
        conn.execute("INSERT OR REPLACE INTO schema_version (version, applied_at) VALUES (?, ?)",
                     (version, clock.now()))
        applied.append(version)
    return applied


def open_db(path, timeout_s=DEFAULT_TIMEOUT_S):
    """connect() + migrate() — the call every process entry point makes."""
    conn = connect(path, timeout_s)
    migrate(conn)
    return conn


def checkpoint(conn):
    """Truncate the WAL so it cannot grow without bound on the SD card."""
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def integrity_check(conn):
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return row[0] if row else "unknown"


def get_meta(conn, key, default=None):
    row = conn.execute("SELECT value FROM gallery_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_meta(conn, key, value):
    """Caller is responsible for being inside a transaction when it matters."""
    cur = conn.execute("UPDATE gallery_meta SET value = ? WHERE key = ?", (str(value), key))
    if cur.rowcount == 0:
        conn.execute("INSERT INTO gallery_meta (key, value) VALUES (?, ?)", (key, str(value)))
