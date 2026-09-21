import sqlite3

import pytest

from edgeface.storage import db, outbox

T0 = 1_700_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def test_enqueue_claim_and_mark_sent(conn):
    with db.transaction(conn):
        eid = outbox.enqueue(conn, "session.closed", {"session_id": "s1"}, at=T0)
    batch = outbox.claim_batch(conn, now=T0)
    assert len(batch) == 1
    assert batch[0]["event_id"] == eid
    assert batch[0]["payload"] == {"session_id": "s1", "schema": outbox.PAYLOAD_SCHEMA}
    with db.transaction(conn):
        assert outbox.mark_sent(conn, [eid], at=T0 + 1) == 1
    assert outbox.claim_batch(conn, now=T0 + 2) == []
    assert outbox.pending_count(conn) == 0


def test_duplicate_event_id_is_refused(conn):
    with db.transaction(conn):
        outbox.enqueue(conn, "session.closed", {}, at=T0, event_id="fixed")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction(conn):
            outbox.enqueue(conn, "session.closed", {}, at=T0, event_id="fixed")


def test_unknown_type_is_refused(conn):
    with pytest.raises(ValueError):
        with db.transaction(conn):
            outbox.enqueue(conn, "gossip", {}, at=T0)


def test_failure_schedules_a_later_attempt(conn):
    with db.transaction(conn):
        eid = outbox.enqueue(conn, "spoof.detected", {"p_real": 0.1}, at=T0)
    with db.transaction(conn):
        next_at = outbox.mark_failed(conn, eid, "connection refused", now=T0,
                                     jitter=0.0, rng=lambda: 0.5)
    assert next_at == T0 + 5.0                       # first retry after base_s
    assert outbox.claim_batch(conn, now=T0 + 1) == []   # not due yet
    assert len(outbox.claim_batch(conn, now=T0 + 6)) == 1
    row = outbox.claim_batch(conn, now=T0 + 6)[0]
    assert row["attempts"] == 1 and "refused" in row["last_error"]


def test_backoff_grows_and_is_capped(conn):
    delays = [outbox.backoff_delay(n, jitter=0.0, rng=lambda: 0.5) for n in range(1, 10)]
    assert delays[:4] == [5.0, 10.0, 20.0, 40.0]
    assert delays[-1] == 600.0                        # capped at max_s
    assert all(b >= a for a, b in zip(delays, delays[1:]))


def test_unsent_events_are_never_purged(conn):
    with db.transaction(conn):
        pending = outbox.enqueue(conn, "session.closed", {}, at=T0)
        sent = outbox.enqueue(conn, "session.closed", {}, at=T0)
        outbox.mark_sent(conn, [sent], at=T0)
    with db.transaction(conn):
        assert outbox.purge_sent(conn, older_than=T0 + 10) == 1
    assert outbox.pending_count(conn) == 1
    assert outbox.claim_batch(conn, now=T0 + 20)[0]["event_id"] == pending


def test_oldest_pending_age(conn):
    assert outbox.oldest_pending_age(conn, now=T0) == 0.0
    with db.transaction(conn):
        outbox.enqueue(conn, "device.heartbeat", {}, at=T0)
        outbox.enqueue(conn, "device.heartbeat", {}, at=T0 + 100)
    assert outbox.oldest_pending_age(conn, now=T0 + 150) == 150.0
