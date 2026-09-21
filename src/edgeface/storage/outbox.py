"""Durable event queue: engine enqueues, sync pushes to the server.

event_id (uuid4) is also the idempotency key on the server, so a retry after a timeout
cannot create a duplicate. Events are never dropped by retention: they are deleted only
after the server has acknowledged them.
"""
import json
import random
import uuid

from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

# Event types the server understands (see docs/plans/M7_server_sync.md).
TYPES = ("enrollment.created", "session.closed", "spoof.detected", "patient.revoked_local",
         "device.heartbeat")

PAYLOAD_SCHEMA = 1


def enqueue(conn, type_, payload, at=None, event_id=None):
    """Queue one event. Must run inside db.transaction() together with what it reports."""
    if type_ not in TYPES:
        raise ValueError("unknown outbox event type: {}".format(type_))
    at = clock.now() if at is None else at
    event_id = event_id or uuid.uuid4().hex
    body = dict(payload or {})
    body.setdefault("schema", PAYLOAD_SCHEMA)
    conn.execute(
        "INSERT INTO outbox (event_id, type, payload, created_at, attempts, next_attempt_at) "
        "VALUES (?, ?, ?, ?, 0, ?)",
        (event_id, type_, json.dumps(body, ensure_ascii=False), at, at))
    return event_id


def claim_batch(conn, limit=50, now=None):
    """Events ready to send: never sent and past their next attempt time."""
    now = clock.now() if now is None else now
    rows = read_all(
        conn, "SELECT * FROM outbox WHERE sent_at IS NULL AND next_attempt_at <= ? "
              "ORDER BY created_at LIMIT ?", (now, limit))
    for row in rows:
        row["payload"] = json.loads(row["payload"])
    return rows


def mark_sent(conn, event_ids, at=None):
    at = clock.now() if at is None else at
    event_ids = list(event_ids)
    if not event_ids:
        return 0
    placeholders = ",".join("?" * len(event_ids))
    return conn.execute(
        "UPDATE outbox SET sent_at = ?, last_error = NULL WHERE event_id IN ({})".format(
            placeholders), [at] + event_ids).rowcount


def backoff_delay(attempts, base_s=5.0, max_s=600.0, jitter=0.2, rng=random.random):
    """Exponential backoff with jitter: 5s, 10s, 20s ... capped at 10 min."""
    delay = min(max_s, base_s * (2 ** max(0, attempts - 1)))
    return delay * (1.0 - jitter + 2 * jitter * rng())


def mark_failed(conn, event_id, error, now=None, base_s=5.0, max_s=600.0, jitter=0.2,
                rng=random.random):
    """Record a failure and schedule the next attempt."""
    now = clock.now() if now is None else now
    row = read_one(conn, "SELECT attempts FROM outbox WHERE event_id = ?", (event_id,))
    if row is None:
        return None
    attempts = int(row["attempts"]) + 1
    next_at = now + backoff_delay(attempts, base_s, max_s, jitter, rng)
    conn.execute(
        "UPDATE outbox SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE event_id = ?",
        (attempts, next_at, (error or "")[:500], event_id))
    return next_at


def pending_count(conn, now=None):
    row = conn.execute("SELECT COUNT(*) AS n FROM outbox WHERE sent_at IS NULL").fetchone()
    return int(row["n"])


def oldest_pending_age(conn, now=None):
    """Seconds since the oldest unsent event was created; 0 when the queue is empty.

    The kiosk status screen shows this: a growing number means sync is stuck.
    """
    now = clock.now() if now is None else now
    row = conn.execute(
        "SELECT MIN(created_at) AS t FROM outbox WHERE sent_at IS NULL").fetchone()
    return 0.0 if row["t"] is None else max(0.0, now - float(row["t"]))


def purge_sent(conn, older_than):
    """Delete acknowledged events only. Unsent events are never purged."""
    return conn.execute("DELETE FROM outbox WHERE sent_at IS NOT NULL AND sent_at < ?",
                        (older_than,)).rowcount
