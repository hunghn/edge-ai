# -*- coding: utf-8 -*-
"""POST /api/v1/events: authentication, idempotency and per-event isolation."""
import base64
import time

import numpy as np


def embedding_b64(seed=0):
    rng = np.random.RandomState(seed)
    vector = rng.randn(512).astype("<f4")
    vector /= np.linalg.norm(vector)
    return base64.b64encode(vector.tobytes()).decode()


def event_id(suffix):
    """Realistic ids: the device sends uuid4 hex, and the schema requires >= 8 chars."""
    return (suffix + "0" * 32)[:32]


def enrollment_event(suffix="enroll1", code="BN001", templates=3):
    return {"event_id": event_id(suffix), "type": "enrollment.created",
            "created_at": time.time(),
            "payload": {"patient_code": code, "full_name": "Nguyễn Thị Hà",
                        "birth_year": 1990, "appointment_code": "AP-" + code,
                        "procedure_date": "2026-09-22",
                        "recognizer_sha256": "sha-mbf",
                        "templates": [{"embedding_b64": embedding_b64(i), "quality": 0.8}
                                      for i in range(templates)]}}


def session_event(suffix="session1", session_id="sess-1"):
    return {"event_id": event_id(suffix), "type": "session.closed", "created_at": time.time(),
            "payload": {"session_id": session_id, "kind": "identify",
                        "started_at": time.time(), "decision": "review_required",
                        "rule_id": "R3", "top1_code": "BN001", "top1_score": 0.91,
                        "votes": 5, "n_good_frames": 5, "nurse_action": "confirm",
                        "confirmed_code": "BN001"}}


def post(client, auth, events):
    return client.post("/api/v1/events",
                       json={"device_id": "kiosk-01", "events": events}, headers=auth)


def test_a_token_is_required(client):
    assert client.post("/api/v1/events",
                       json={"device_id": "kiosk-01", "events": []}).status_code == 401
    assert client.post("/api/v1/events", json={"device_id": "kiosk-01", "events": []},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_enrollment_creates_patient_and_templates(client, auth):
    body = post(client, auth, [enrollment_event()]).json()
    assert body["accepted"] == [event_id("enroll1")] and body["rejected"] == []

    from server.db import session_scope
    from server.models import Appointment, FaceTemplate, GalleryVersion, Patient

    with session_scope() as session:
        patient = session.get(Patient, "BN001")
        assert patient.full_name == "Nguyễn Thị Hà"
        assert session.query(FaceTemplate).filter(
            FaceTemplate.patient_code == "BN001").count() == 3
        assert session.get(Appointment, "AP-BN001").procedure_date == "2026-09-22"
        assert session.get(GalleryVersion, "2026-09-22").version == 1


def test_resending_the_same_batch_changes_nothing(client, auth):
    """The device retries after a timeout; the server must not double anything."""
    first = post(client, auth, [enrollment_event(), session_event()]).json()
    assert len(first["accepted"]) == 2

    second = post(client, auth, [enrollment_event(), session_event()]).json()
    assert sorted(second["duplicate"]) == sorted([event_id("enroll1"), event_id("session1")])
    assert second["accepted"] == []

    from server.db import session_scope
    from server.models import FaceTemplate, SessionLog

    with session_scope() as session:
        assert session.query(FaceTemplate).count() == 3      # not 6
        assert session.query(SessionLog).count() == 1


def test_re_enrolling_replaces_the_devices_templates(client, auth):
    post(client, auth, [enrollment_event("first", templates=3)])
    post(client, auth, [enrollment_event("second", templates=5)])

    from server.db import session_scope
    from server.models import FaceTemplate

    with session_scope() as session:
        assert session.query(FaceTemplate).filter(
            FaceTemplate.patient_code == "BN001").count() == 5


def test_one_bad_event_does_not_block_the_batch(client, auth):
    """Otherwise a single malformed payload would wedge the queue forever."""
    broken = enrollment_event("broken")
    broken["payload"]["templates"] = [{"embedding_b64": base64.b64encode(b"short").decode()}]
    unknown = {"event_id": event_id("unknown"), "type": "gossip",
               "created_at": time.time(), "payload": {}}
    body = post(client, auth, [broken, session_event(), unknown]).json()

    assert body["accepted"] == [event_id("session1")]
    rejected = {row["event_id"]: row["error"] for row in body["rejected"]}
    assert "expected 2048" in rejected[event_id("broken")]
    assert "unknown type" in rejected[event_id("unknown")]


def test_session_and_spoof_events_are_stored(client, auth):
    spoof = {"event_id": event_id("spoof1"), "type": "spoof.detected",
             "created_at": time.time(),
             "payload": {"session_id": "sess-1", "min_p_real": 0.12, "spoof_frames": 3,
                         "evidence_sha256": "a" * 64}}
    post(client, auth, [session_event(), spoof])

    from server.db import session_scope
    from server.models import SessionLog, SpoofEvent

    with session_scope() as session:
        log = session.get(SessionLog, "sess-1")
        assert log.decision == "review_required" and log.nurse_action == "confirm"
        assert log.device_id == "kiosk-01"
        assert session.get(SpoofEvent, event_id("spoof1")).min_p_real == 0.12


def test_revocation_from_the_device(client, auth):
    post(client, auth, [enrollment_event()])
    revoke = {"event_id": event_id("revoke1"), "type": "patient.revoked_local",
              "created_at": time.time(),
              "payload": {"patient_code": "BN001", "reason": "nurse"}}
    assert post(client, auth, [revoke]).json()["accepted"] == [event_id("revoke1")]

    from server.db import session_scope
    from server.models import Patient, Revocation

    with session_scope() as session:
        assert session.get(Patient, "BN001").revoked_at is not None
        assert session.get(Revocation, "BN001").reason == "nurse"


def test_batch_size_limit(client, auth):
    events = [enrollment_event("bulk{}".format(i)) for i in range(200)]
    assert post(client, auth, events).status_code == 413


def test_heartbeat_updates_the_device_row(client, auth):
    response = client.post("/api/v1/devices/heartbeat",
                           json={"gallery_version": 7, "model_version": "2026-09-22"},
                           headers=auth)
    assert response.status_code == 200 and response.json()["ok"] is True

    from server.db import session_scope
    from server.models import Device

    with session_scope() as session:
        device = session.get(Device, "kiosk-01")
        assert device.last_gallery_version == 7 and device.last_seen_at is not None
