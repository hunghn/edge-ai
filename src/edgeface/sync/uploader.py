"""Push outbox events to the server.

The contract with the outbox: an event leaves the device exactly once from the server's
point of view (idempotency by event_id) and is deleted locally only after the server
acknowledges it. A rejected event is kept and logged, never silently dropped.
"""
from edgeface.common.log import get_logger
from edgeface.storage import clock, outbox
from edgeface.storage.db import transaction
from edgeface.sync.client import ServerError

LOG = get_logger("sync.upload")


def upload_once(conn, client, batch_size=50, now=None, backoff=None):
    """Send one batch. Returns {"sent", "duplicate", "rejected", "pending", "error"}."""
    now = clock.now() if now is None else now
    backoff = backoff or {}
    rows = outbox.claim_batch(conn, limit=batch_size, now=now)
    result = {"sent": 0, "duplicate": 0, "rejected": 0,
              "pending": outbox.pending_count(conn), "error": None}
    if not rows:
        return result

    events = [{"event_id": row["event_id"], "type": row["type"],
               "created_at": row["created_at"], "payload": row["payload"]} for row in rows]
    try:
        answer = client.post_events(events)
    except ServerError as exc:
        # The whole batch stays queued; each event gets its own backoff so a permanent
        # problem with one of them cannot stall everything behind it forever.
        with transaction(conn):
            for row in rows:
                outbox.mark_failed(conn, row["event_id"], str(exc), now,
                                   base_s=backoff.get("base_s", 5.0),
                                   max_s=backoff.get("max_s", 600.0),
                                   jitter=backoff.get("jitter", 0.2))
        result["error"] = str(exc)
        result["pending"] = outbox.pending_count(conn)
        LOG.warning("upload failed (%d events kept): %s", len(rows), exc)
        return result

    accepted = list(answer.get("accepted") or [])
    duplicate = list(answer.get("duplicate") or [])
    rejected = answer.get("rejected") or []
    with transaction(conn):
        if accepted or duplicate:
            # A duplicate means the server already has it: as good as sent.
            outbox.mark_sent(conn, accepted + duplicate, now)
        for item in rejected:
            outbox.mark_failed(conn, item.get("event_id"), item.get("error", "rejected"),
                               now, base_s=backoff.get("base_s", 5.0),
                               max_s=backoff.get("max_s", 600.0),
                               jitter=backoff.get("jitter", 0.2))
    for item in rejected:
        LOG.error("server rejected event %s: %s", item.get("event_id"), item.get("error"))

    result.update({"sent": len(accepted), "duplicate": len(duplicate),
                   "rejected": len(rejected), "pending": outbox.pending_count(conn)})
    LOG.info("uploaded %d, duplicate %d, rejected %d, pending %d",
             result["sent"], result["duplicate"], result["rejected"], result["pending"])
    return result


def drain(conn, client, batch_size=50, max_batches=20, now=None, backoff=None):
    """Keep sending until the queue is empty, an error occurs or max_batches is reached."""
    totals = {"sent": 0, "duplicate": 0, "rejected": 0, "batches": 0, "error": None}
    for _ in range(max_batches):
        result = upload_once(conn, client, batch_size, now, backoff)
        totals["batches"] += 1
        for key in ("sent", "duplicate", "rejected"):
            totals[key] += result[key]
        if result["error"]:
            totals["error"] = result["error"]
            break
        if result["sent"] + result["duplicate"] + result["rejected"] == 0:
            break
    return totals
