import numpy as np
import pytest

from edgeface.gallery import retention
from edgeface.storage import db, evidence, metrics, outbox, patients, sessions, templates

T0 = 1_700_000_000.0
HOUR = 3600.0
DAY = 86400.0
SHA = "sha-model-a"
CFG = {"retention": {"sessions_days": 30, "metrics_days": 30}}


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


@pytest.fixture
def evidence_dir(tmp_path):
    return str(tmp_path / "evidence")


def enroll(conn, code, at=T0, ttl_hours=24):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, code, 1990, "kiosk", at, ttl_hours)
        templates.add_templates(conn, code, [np.zeros(512, dtype=np.float32)], SHA,
                                created_at=at)


def test_expired_patients_and_their_templates_go(conn, evidence_dir):
    enroll(conn, "BN001", at=T0)
    enroll(conn, "BN002", at=T0 + 12 * HOUR)
    result = retention.run_once(conn, CFG, now=T0 + 25 * HOUR, evidence_dir=evidence_dir)
    assert result["patients_expired"] == 1
    assert templates.count(conn) == 1
    assert [c for c, in conn.execute("SELECT patient_code FROM patients")] == ["BN002"]


def test_gallery_version_bumps_only_when_something_was_deleted(conn, evidence_dir):
    enroll(conn, "BN001", at=T0)
    version_before = templates.gallery_version(conn)
    quiet = retention.run_once(conn, CFG, now=T0 + HOUR, evidence_dir=evidence_dir)
    assert "gallery_version" not in quiet
    assert templates.gallery_version(conn) == version_before
    loud = retention.run_once(conn, CFG, now=T0 + 25 * HOUR, evidence_dir=evidence_dir)
    assert loud["gallery_version"] == version_before + 1


def test_revocations_are_applied(conn, evidence_dir):
    enroll(conn, "BN001", at=T0)
    with db.transaction(conn):
        patients.revoke(conn, "BN001", "server", T0 + 60)
    result = retention.run_once(conn, CFG, now=T0 + HOUR, evidence_dir=evidence_dir)
    assert result["patients_revoked"] == 1
    assert patients.get(conn, "BN001") is None and templates.count(conn) == 0


def test_sessions_metrics_and_sent_events_expire(conn, evidence_dir):
    with db.transaction(conn):
        sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0, ttl_days=30)
        metrics.add_latency_batch(conn, [("S1", 12.0)], session_id=sid, ts=T0)
        sent = outbox.enqueue(conn, "session.closed", {}, at=T0)
        outbox.mark_sent(conn, [sent], at=T0)
        pending = outbox.enqueue(conn, "session.closed", {}, at=T0)
    result = retention.run_once(conn, CFG, now=T0 + 31 * DAY, evidence_dir=evidence_dir)
    assert result["sessions"] == 1 and result["metrics"] == 1 and result["outbox_sent"] == 1
    assert outbox.pending_count(conn) == 1      # unsent events survive
    assert outbox.claim_batch(conn, now=T0 + 31 * DAY)[0]["event_id"] == pending


def test_expired_evidence_files_are_deleted(conn, evidence_dir):
    with db.transaction(conn):
        evidence.save(conn, None, b"jpeg", evidence_dir, ttl_days=7, at=T0)
    result = retention.run_once(conn, CFG, now=T0 + 8 * DAY, evidence_dir=evidence_dir)
    assert result["evidence_files"] == 1 and result["evidence_rows"] == 1
    assert evidence.count(conn) == 0


def test_clock_going_backwards_skips_the_run(conn, evidence_dir):
    enroll(conn, "BN001", at=T0)
    retention.run_once(conn, CFG, now=T0 + HOUR, evidence_dir=evidence_dir)      # records last run
    result = retention.run_once(conn, CFG, now=T0 - 10 * DAY, evidence_dir=evidence_dir)
    assert result == {"skipped": "clock_went_backwards"}
    assert patients.get(conn, "BN001") is not None                               # nothing deleted


def test_clock_jumping_far_forward_skips_the_run(conn, evidence_dir):
    enroll(conn, "BN001", at=T0)
    retention.run_once(conn, CFG, now=T0 + HOUR, evidence_dir=evidence_dir)
    result = retention.run_once(conn, CFG, now=T0 + 400 * DAY, evidence_dir=evidence_dir)
    assert result == {"skipped": "clock_jumped_forward"}
    assert patients.get(conn, "BN001") is not None
    # ... unless the operator forces it
    forced = retention.run_once(conn, CFG, now=T0 + 400 * DAY, evidence_dir=evidence_dir,
                                force=True)
    assert forced["patients_expired"] == 1


def test_due_respects_the_interval(conn, evidence_dir):
    assert retention.due(conn, now=T0) is True          # never ran
    retention.run_once(conn, CFG, now=T0, evidence_dir=evidence_dir)
    assert retention.due(conn, now=T0 + 60, interval_s=600) is False
    assert retention.due(conn, now=T0 + 601, interval_s=600) is True
