"""Three processes hammering one SQLite file, like engine + kiosk + sync on the Nano.

The point is the guarantee the whole runtime architecture rests on: WAL plus a busy
timeout plus short BEGIN IMMEDIATE transactions must never surface "database is locked"
to the callers, lose a command, or lose an outbox event.
"""
import multiprocessing
import os
import time

import pytest

from edgeface.storage import db, kiosk_ipc, metrics, outbox, sessions

DURATION_S = float(os.environ.get("EDGEFACE_CONCURRENCY_SECONDS", "6"))
ENGINE_HZ = 15.0
KIOSK_HZ = 10.0
SYNC_HZ = 2.0


def _engine(path, duration_s, result):
    """Publishes kiosk state, opens/closes sessions, writes metrics and outbox events."""
    conn = db.open_db(path)
    errors, published, events = 0, 0, 0
    deadline = time.time() + duration_s
    while time.time() < deadline:
        try:
            with db.transaction(conn):
                kiosk_ipc.publish_state(conn, "GUIDING", "STEP_CLOSER")
                published += 1
            with db.transaction(conn):
                sid = sessions.open_session(conn, sessions.KIND_IDENTIFY)
                metrics.add_latency_batch(conn, [("S1", 12.3), ("S4", 6.1)], session_id=sid)
                sessions.close_session(conn, sid, decision="review_required", rule_id="R3",
                                       nurse_action="confirm")
                outbox.enqueue(conn, "session.closed", {"session_id": sid})
                events += 1
            kiosk_ipc.claim_commands(conn)
        except Exception as exc:  # noqa: BLE001 - the test records what went wrong
            errors += 1
            result["engine_error"] = repr(exc)
        time.sleep(1.0 / ENGINE_HZ)
    conn.close()
    result["engine_errors"] = errors
    result["published"] = published
    result["events"] = events


def _kiosk(path, duration_s, result):
    """Polls the state row and sends a command every poll."""
    conn = db.open_db(path)
    errors, reads, sent, last_seq = 0, 0, 0, -1
    deadline = time.time() + duration_s
    while time.time() < deadline:
        try:
            state = kiosk_ipc.read_state(conn, after_seq=last_seq)
            if state is not None:
                last_seq = state["seq"]
                reads += 1
            with db.transaction(conn):
                kiosk_ipc.send_command(conn, "retry", {"n": sent})
                sent += 1
        except Exception as exc:  # noqa: BLE001
            errors += 1
            result["kiosk_error"] = repr(exc)
        time.sleep(1.0 / KIOSK_HZ)
    conn.close()
    result["kiosk_errors"] = errors
    result["reads"] = reads
    result["commands_sent"] = sent


def _sync(path, duration_s, result):
    """Claims outbox batches and marks them sent, like the uploader does."""
    conn = db.open_db(path)
    errors, marked = 0, 0
    deadline = time.time() + duration_s
    while time.time() < deadline:
        try:
            batch = outbox.claim_batch(conn, limit=20)
            if batch:
                with db.transaction(conn):
                    marked += outbox.mark_sent(conn, [row["event_id"] for row in batch])
        except Exception as exc:  # noqa: BLE001
            errors += 1
            result["sync_error"] = repr(exc)
        time.sleep(1.0 / SYNC_HZ)
    conn.close()
    result["sync_errors"] = errors
    result["marked_sent"] = marked


@pytest.mark.slow
def test_three_processes_share_the_database(tmp_path):
    path = str(tmp_path / "edge.db")
    db.open_db(path).close()          # create the schema before the children start

    manager = multiprocessing.Manager()
    result = manager.dict()
    procs = [multiprocessing.Process(target=target, args=(path, DURATION_S, result))
             for target in (_engine, _kiosk, _sync)]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(DURATION_S + 60)

    assert all(proc.exitcode == 0 for proc in procs), [p.exitcode for p in procs]
    data = dict(result)
    assert data.get("engine_errors") == 0, data.get("engine_error")
    assert data.get("kiosk_errors") == 0, data.get("kiosk_error")
    assert data.get("sync_errors") == 0, data.get("sync_error")

    # Real work happened, not just an idle loop.
    assert data["published"] > 10 and data["events"] > 10
    assert data["reads"] > 5 and data["commands_sent"] > 5

    conn = db.open_db(path)
    try:
        assert db.integrity_check(conn) == "ok"
        # No command is lost: every one was either consumed by the engine or still pending.
        consumed = conn.execute(
            "SELECT COUNT(*) AS n FROM kiosk_commands WHERE consumed_at IS NOT NULL"
        ).fetchone()["n"]
        total_commands = conn.execute("SELECT COUNT(*) AS n FROM kiosk_commands").fetchone()["n"]
        assert total_commands == data["commands_sent"]
        assert consumed + kiosk_ipc.pending_commands(conn) == total_commands
        # Every event is accounted for, and none was sent twice.
        sent_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM outbox WHERE sent_at IS NOT NULL").fetchone()["n"]
        assert sent_rows == data["marked_sent"]
        assert sent_rows + outbox.pending_count(conn) == data["events"]
        # The state row kept its invariant: exactly one row, seq equal to the publish count.
        state = conn.execute("SELECT seq, COUNT(*) AS rows FROM kiosk_state").fetchone()
        assert state["rows"] == 1 and state["seq"] == data["published"]
    finally:
        conn.close()
