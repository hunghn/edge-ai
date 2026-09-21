import pytest

from edgeface.storage import db, kiosk_ipc

T0 = 1_700_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def test_publish_increments_seq_and_read_only_returns_changes(conn):
    assert kiosk_ipc.read_state(conn, after_seq=-1)["state"] == "IDLE"   # seeded by migration
    with db.transaction(conn):
        seq1 = kiosk_ipc.publish_state(conn, "GUIDING", "STEP_CLOSER", at=T0)
    assert seq1 == 1
    state = kiosk_ipc.read_state(conn, after_seq=0)
    assert state["state"] == "GUIDING" and state["guidance_code"] == "STEP_CLOSER"
    assert kiosk_ipc.read_state(conn, after_seq=seq1) is None            # nothing new
    with db.transaction(conn):
        seq2 = kiosk_ipc.publish_state(conn, "AWAIT_NURSE", session_id="s1",
                                       payload={"candidate": {"code": "BN001"}}, at=T0 + 1)
    assert seq2 == 2
    state = kiosk_ipc.read_state(conn, after_seq=seq1)
    assert state["payload"]["candidate"]["code"] == "BN001"


def test_unknown_state_or_command_is_rejected(conn):
    with pytest.raises(ValueError):
        with db.transaction(conn):
            kiosk_ipc.publish_state(conn, "DANCING")
    with pytest.raises(ValueError):
        with db.transaction(conn):
            kiosk_ipc.send_command(conn, "self_destruct")


def test_commands_are_claimed_exactly_once(conn):
    with db.transaction(conn):
        kiosk_ipc.send_command(conn, "confirm", {"code": "BN001"}, session_id="s1", at=T0)
        kiosk_ipc.send_command(conn, "retry", at=T0 + 1)
    assert kiosk_ipc.pending_commands(conn) == 2

    first = kiosk_ipc.claim_commands(conn, at=T0 + 2)
    assert [c["type"] for c in first] == ["confirm", "retry"]
    assert first[0]["payload"] == {"code": "BN001"}
    assert first[0]["session_id"] == "s1"
    assert kiosk_ipc.claim_commands(conn, at=T0 + 3) == []               # already consumed
    assert kiosk_ipc.pending_commands(conn) == 0


def test_claim_respects_limit_and_order(conn):
    with db.transaction(conn):
        for i in range(5):
            kiosk_ipc.send_command(conn, "retry", {"i": i}, at=T0 + i)
    batch = kiosk_ipc.claim_commands(conn, limit=2, at=T0 + 10)
    assert [c["payload"]["i"] for c in batch] == [0, 1]
    assert [c["payload"]["i"] for c in kiosk_ipc.claim_commands(conn, at=T0 + 11)] == [2, 3, 4]


def test_purge_consumed(conn):
    with db.transaction(conn):
        kiosk_ipc.send_command(conn, "retry", at=T0)
    kiosk_ipc.claim_commands(conn, at=T0 + 1)
    with db.transaction(conn):
        kiosk_ipc.send_command(conn, "confirm", {"code": "BN001"}, at=T0 + 2)
    with db.transaction(conn):
        assert kiosk_ipc.purge_consumed(conn, older_than=T0 + 5) == 1
    assert kiosk_ipc.pending_commands(conn) == 1
