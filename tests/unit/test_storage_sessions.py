import pytest

from edgeface.storage import db, sessions

T0 = 1_700_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def test_open_update_close(conn):
    with db.transaction(conn):
        sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0, ttl_days=30)
    with db.transaction(conn):
        sessions.update_session(conn, sid, top1_code="BN001", top1_score=0.71, votes=4)
        sessions.close_session(conn, sid, ended_at=T0 + 3, decision="review_required",
                               rule_id="R3", nurse_action="confirm", confirmed_code="BN001")
    row = sessions.get(conn, sid)
    assert row["kind"] == "identify" and row["ended_at"] == T0 + 3
    assert row["decision"] == "review_required" and row["nurse_action"] == "confirm"
    assert row["expires_at"] == T0 + 30 * 86400.0


def test_unknown_columns_and_actions_are_rejected(conn):
    with db.transaction(conn):
        sid = sessions.open_session(conn, sessions.KIND_ENROLL, T0)
    with pytest.raises(ValueError):
        sessions.update_session(conn, sid, patient_code="BN001")     # not an updatable column
    with pytest.raises(ValueError):
        sessions.update_session(conn, sid, nurse_action="approve")   # not a known action
    with pytest.raises(ValueError):
        with db.transaction(conn):
            sessions.open_session(conn, "browse", T0)


def test_close_dangling_after_a_crash(conn):
    with db.transaction(conn):
        open_sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0)
        closed_sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0)
        sessions.close_session(conn, closed_sid, ended_at=T0 + 1, nurse_action="reject")
    with db.transaction(conn):
        assert sessions.close_dangling(conn, now=T0 + 100) == 1
    assert sessions.get(conn, open_sid)["nurse_action"] == "cancel"
    assert sessions.get(conn, closed_sid)["nurse_action"] == "reject"


def test_purge_expired(conn):
    with db.transaction(conn):
        old = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0, ttl_days=1)
        new = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0, ttl_days=30)
    with db.transaction(conn):
        assert sessions.purge_expired(conn, T0 + 2 * 86400.0) == 1
    assert sessions.get(conn, old) is None and sessions.get(conn, new) is not None


def test_stats_counts_decisions_and_actions(conn):
    with db.transaction(conn):
        for decision, action in (("review_required", "confirm"), ("review_required", "reject"),
                                 ("low_quality", "retry")):
            sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0)
            sessions.close_session(conn, sid, ended_at=T0 + 1, decision=decision,
                                   nurse_action=action)
    stats = sessions.stats(conn, since=T0 - 1)
    assert stats["total"] == 3
    assert stats["by_decision"] == {"review_required": 2, "low_quality": 1}
    assert stats["by_nurse_action"] == {"confirm": 1, "reject": 1, "retry": 1}
