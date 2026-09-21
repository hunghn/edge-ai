"""Identification and enrollment sessions.

A session row is the audit trail of one attempt: decision, scores, what the nurse did.
It never contains an image. Rows expire after retention.sessions_days (C-17).
"""
import uuid

from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

KIND_IDENTIFY = "identify"
KIND_ENROLL = "enroll"
NURSE_ACTIONS = ("confirm", "reject", "retry", "manual", "timeout", "cancel")

# Columns update_session()/close_session() may write. Anything else is a programming error.
_UPDATABLE = frozenset([
    "decision", "rule_id", "top1_code", "top1_score", "top2_code", "top2_score", "votes",
    "n_good_frames", "min_p_real", "spoof_frames", "nurse_action", "confirmed_code",
    "operator_id", "ended_at",
])


def open_session(conn, kind, started_at=None, ttl_days=30, session_id=None):
    if kind not in (KIND_IDENTIFY, KIND_ENROLL):
        raise ValueError("unknown session kind: {}".format(kind))
    started_at = clock.now() if started_at is None else started_at
    session_id = session_id or uuid.uuid4().hex
    conn.execute(
        "INSERT INTO sessions (session_id, kind, started_at, expires_at) VALUES (?, ?, ?, ?)",
        (session_id, kind, started_at, started_at + ttl_days * 86400.0))
    return session_id


def update_session(conn, session_id, **fields):
    unknown = set(fields) - _UPDATABLE
    if unknown:
        raise ValueError("cannot update session columns: {}".format(sorted(unknown)))
    if not fields:
        return 0
    action = fields.get("nurse_action")
    if action is not None and action not in NURSE_ACTIONS:
        raise ValueError("unknown nurse_action: {}".format(action))
    names = sorted(fields)
    assignments = ", ".join("{} = ?".format(name) for name in names)
    params = [fields[name] for name in names] + [session_id]
    return conn.execute(
        "UPDATE sessions SET {} WHERE session_id = ?".format(assignments), params).rowcount


def close_session(conn, session_id, ended_at=None, **fields):
    fields["ended_at"] = clock.now() if ended_at is None else ended_at
    return update_session(conn, session_id, **fields)


def close_dangling(conn, now=None, reason="cancel"):
    """Close sessions left open by a crash. Called at engine start-up."""
    now = clock.now() if now is None else now
    return conn.execute(
        "UPDATE sessions SET ended_at = ?, nurse_action = ? WHERE ended_at IS NULL",
        (now, reason)).rowcount


def get(conn, session_id):
    return read_one(conn, "SELECT * FROM sessions WHERE session_id = ?", (session_id,))


def recent(conn, limit=50, kind=None):
    if kind is None:
        return read_all(conn, "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,))
    return read_all(conn, "SELECT * FROM sessions WHERE kind = ? ORDER BY started_at DESC "
                          "LIMIT ?", (kind, limit))


def purge_expired(conn, now=None):
    now = clock.now() if now is None else now
    return conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,)).rowcount


def stats(conn, since=None):
    """Counts per decision and per nurse action — the operational metrics of spec §5."""
    since = 0.0 if since is None else since
    decisions = read_all(
        conn, "SELECT decision, COUNT(*) AS n FROM sessions WHERE started_at >= ? "
              "GROUP BY decision", (since,))
    actions = read_all(
        conn, "SELECT nurse_action, COUNT(*) AS n FROM sessions WHERE started_at >= ? "
              "GROUP BY nurse_action", (since,))
    total = conn.execute("SELECT COUNT(*) AS n FROM sessions WHERE started_at >= ?",
                         (since,)).fetchone()["n"]
    return {
        "total": int(total),
        "by_decision": {row["decision"]: int(row["n"]) for row in decisions},
        "by_nurse_action": {row["nurse_action"]: int(row["n"]) for row in actions},
    }
