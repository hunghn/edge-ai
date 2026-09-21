"""IPC between the engine and the kiosk, over SQLite instead of sockets.

engine -> kiosk : kiosk_state, a single row whose seq increases on every publish. The
                  kiosk polls with the last seq it saw and only redraws on a change.
kiosk -> engine : kiosk_commands, an append-only queue. claim_commands() marks rows
                  consumed inside the same transaction that reads them, so one command
                  is never executed twice.
"""
import json

from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one, transaction

# Engine states the kiosk knows how to render (see docs/plans/M5_engine_session.md).
STATES = ("IDLE", "GUIDING", "COLLECTING", "DECIDED", "AWAIT_NURSE", "COOLDOWN",
          "ENROLL_GUIDING", "ENROLL_COLLECTING", "ENROLL_REVIEW", "ENROLL_ERROR",
          "CAMERA_ERROR")

# Commands the kiosk may send.
COMMANDS = ("confirm", "reject", "retry", "manual", "start_enroll", "enroll_confirm",
            "enroll_cancel", "revoke", "cancel")


def publish_state(conn, state, guidance_code=None, session_id=None, payload=None, at=None):
    """Engine-side: overwrite the state row and bump seq. Returns the new seq."""
    if state not in STATES:
        raise ValueError("unknown kiosk state: {}".format(state))
    at = clock.now() if at is None else at
    body = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    conn.execute(
        "UPDATE kiosk_state SET seq = seq + 1, state = ?, guidance_code = ?, session_id = ?, "
        "payload = ?, updated_at = ? WHERE id = 1",
        (state, guidance_code, session_id, body, at))
    return int(conn.execute("SELECT seq FROM kiosk_state WHERE id = 1").fetchone()["seq"])


def read_state(conn, after_seq=-1):
    """Kiosk-side: the state row if it changed since after_seq, else None."""
    row = read_one(conn, "SELECT * FROM kiosk_state WHERE id = 1 AND seq > ?", (after_seq,))
    if row is None:
        return None
    row["payload"] = json.loads(row["payload"]) if row["payload"] else None
    return row


def send_command(conn, type_, payload=None, session_id=None, at=None):
    """Kiosk-side: queue a command for the engine. Returns its id."""
    if type_ not in COMMANDS:
        raise ValueError("unknown kiosk command: {}".format(type_))
    at = clock.now() if at is None else at
    body = json.dumps(payload, ensure_ascii=False) if payload is not None else None
    cur = conn.execute(
        "INSERT INTO kiosk_commands (type, payload, session_id, created_at) VALUES (?, ?, ?, ?)",
        (type_, body, session_id, at))
    return int(cur.lastrowid)


def claim_commands(conn, limit=10, at=None):
    """Engine-side: fetch pending commands and mark them consumed atomically."""
    at = clock.now() if at is None else at
    with transaction(conn):
        rows = read_all(
            conn, "SELECT * FROM kiosk_commands WHERE consumed_at IS NULL ORDER BY cmd_id "
                  "LIMIT ?", (limit,))
        for row in rows:
            conn.execute("UPDATE kiosk_commands SET consumed_at = ? WHERE cmd_id = ?",
                         (at, row["cmd_id"]))
    for row in rows:
        row["payload"] = json.loads(row["payload"]) if row["payload"] else None
        row["consumed_at"] = at
    return rows


def pending_commands(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM kiosk_commands WHERE consumed_at IS NULL").fetchone()
    return int(row["n"])


def purge_consumed(conn, older_than):
    return conn.execute(
        "DELETE FROM kiosk_commands WHERE consumed_at IS NOT NULL AND consumed_at < ?",
        (older_than,)).rowcount
