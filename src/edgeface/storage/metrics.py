"""Per-stage latency samples, written in batches by the engine.

Writing one row per stage per frame would hammer the SD card, so the engine buffers and
flushes once per session (or every few seconds).
"""
from edgeface.storage import clock
from edgeface.storage.db import read_all


def add_latency_batch(conn, rows, session_id=None, ts=None):
    """rows: iterable of (stage, ms) or dicts with stage/ms/ts/session_id."""
    ts = clock.now() if ts is None else ts
    prepared = []
    for row in rows:
        if isinstance(row, dict):
            prepared.append((row.get("ts", ts), row.get("session_id", session_id),
                             row["stage"], float(row["ms"])))
        else:
            stage, ms = row
            prepared.append((ts, session_id, stage, float(ms)))
    conn.executemany(
        "INSERT INTO stage_latency (ts, session_id, stage, ms) VALUES (?, ?, ?, ?)", prepared)
    return len(prepared)


def summary(conn, since=None, stage=None):
    """Count/mean/min/max per stage. Percentiles are computed offline in M9 (SQLite 3.22
    has no window functions, and the tools/eval scripts need the raw rows anyway)."""
    since = 0.0 if since is None else since
    if stage is None:
        rows = read_all(conn, "SELECT stage, COUNT(*) AS n, AVG(ms) AS mean, MIN(ms) AS min, "
                              "MAX(ms) AS max FROM stage_latency WHERE ts >= ? GROUP BY stage "
                              "ORDER BY stage", (since,))
    else:
        rows = read_all(conn, "SELECT stage, COUNT(*) AS n, AVG(ms) AS mean, MIN(ms) AS min, "
                              "MAX(ms) AS max FROM stage_latency WHERE ts >= ? AND stage = ? "
                              "GROUP BY stage", (since, stage))
    return {row["stage"]: {"n": int(row["n"]), "mean": row["mean"],
                           "min": row["min"], "max": row["max"]} for row in rows}


def samples(conn, since=None, limit=100000):
    since = 0.0 if since is None else since
    return read_all(conn, "SELECT * FROM stage_latency WHERE ts >= ? ORDER BY ts LIMIT ?",
                    (since, limit))


def purge_older_than(conn, cutoff):
    return conn.execute("DELETE FROM stage_latency WHERE ts < ?", (cutoff,)).rowcount
