"""Enrollment: form validation, the duplicate warning and the commit transaction."""
import os

import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.engine import enroll
from edgeface.gallery.gallery import Gallery
from edgeface.storage import db, outbox, patients, templates
from edgeface.types import Embedding

SHA = "sha-model-a"
T0 = 1_700_000_000.0


@pytest.fixture
def cfg(repo_root):
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def unit(seed):
    rng = np.random.RandomState(seed)
    v = rng.randn(512).astype(np.float32)
    return v / np.linalg.norm(v)


def near(vector, sigma, seed):
    rng = np.random.RandomState(seed)
    out = vector + rng.randn(512).astype(np.float32) * (sigma / np.sqrt(512.0))
    return (out / np.linalg.norm(out)).astype(np.float32)


def embeddings_of(vectors, quality=0.8):
    return [Embedding(i, float(i), v, quality, 21.0) for i, v in enumerate(vectors)]


def form(code="BN001", name="Nguyễn Thị Hà", **extra):
    base = {"patient_code": code, "full_name": name, "birth_year": 1990}
    base.update(extra)
    return base


def existing(conn, code, vector, at=T0):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, code, 1990, "kiosk", at)
        templates.add_templates(conn, code, [vector], SHA, created_at=at)


def test_form_validation():
    assert enroll.validate_form(form()) == (True, None)
    assert enroll.validate_form({})[1] == "missing_form"
    assert enroll.validate_form({"full_name": "A"})[1] == "missing_patient_code"
    assert enroll.validate_form({"patient_code": "BN1"})[1] == "missing_full_name"
    assert enroll.validate_form(form(birth_year="abcd"))[1] == "bad_birth_year"
    assert enroll.validate_form(form(birth_year=1200))[1] == "bad_birth_year"


def test_self_consistency_detects_a_mixed_capture():
    one = unit(1)
    tight = enroll.self_consistency([near(one, 0.2, s) for s in range(5)])
    mixed = enroll.self_consistency([one, unit(2), unit(3), unit(4), unit(5)])
    assert tight > 0.9 > mixed
    assert enroll.self_consistency([one]) is None


def test_review_warns_about_a_duplicate_face(conn, cfg):
    existing(conn, "BN_OLD", unit(7))
    gallery = Gallery(SHA).load(conn, T0)
    calibrated = dict(cfg)
    calibrated["match"] = dict(cfg["match"], threshold=0.5)

    duplicate = enroll.review(form("BN_NEW"), embeddings_of([near(unit(7), 0.2, s)
                                                            for s in range(5)]),
                              gallery, calibrated)
    assert "duplicate_face" in duplicate.warnings
    assert duplicate.duplicate_code == "BN_OLD" and duplicate.duplicate_score > 0.5
    assert duplicate.blocked is False            # C-22: warn, then let the nurse decide

    other = enroll.review(form("BN_NEW"), embeddings_of([near(unit(42), 0.2, s)
                                                         for s in range(5)]),
                          gallery, calibrated)
    assert "duplicate_face" not in other.warnings


def test_duplicate_policy_block(conn, cfg):
    existing(conn, "BN_OLD", unit(7))
    strict = dict(cfg)
    strict["match"] = dict(cfg["match"], threshold=0.5)
    strict["enroll"] = dict(cfg["enroll"], duplicate_policy="block")
    review = enroll.review(form("BN_NEW"), embeddings_of([near(unit(7), 0.2, s)
                                                          for s in range(5)]),
                           Gallery(SHA).load(conn, T0), strict)
    assert review.blocked is True


def test_review_without_a_calibrated_threshold(conn, cfg):
    """D-01 still null: show the closest patient instead of claiming a duplicate."""
    existing(conn, "BN_OLD", unit(7))
    review = enroll.review(form("BN_NEW"), embeddings_of([near(unit(7), 0.2, s)
                                                          for s in range(5)]),
                           Gallery(SHA).load(conn, T0), cfg)
    assert review.warnings == ["duplicate_unknown_threshold"]
    assert review.duplicate_code == "BN_OLD" and review.blocked is False


def test_re_enrolling_the_same_code_is_not_a_duplicate(conn, cfg):
    existing(conn, "BN001", unit(7))
    calibrated = dict(cfg)
    calibrated["match"] = dict(cfg["match"], threshold=0.5)
    review = enroll.review(form("BN001"), embeddings_of([near(unit(7), 0.2, s)
                                                         for s in range(5)]),
                           Gallery(SHA).load(conn, T0), calibrated)
    assert "duplicate_face" not in review.warnings


def test_commit_writes_patient_templates_and_event_atomically(conn, cfg):
    vectors = [near(unit(3), 0.2, s) for s in range(5)]
    result = enroll.commit(conn, form(appointment_code="AP1"), embeddings_of(vectors), cfg,
                           SHA, operator_id=7, now=T0, session_id="sess-1")
    assert result["n_templates"] == 5

    patient = patients.get_with_appointment(conn, "BN001", None)
    assert patient["full_name"] == "Nguyễn Thị Hà" and patient["source"] == "kiosk"
    assert patient["expires_at"] == T0 + cfg["retention"]["patients_hours"] * 3600.0
    assert templates.count(conn, "BN001") == 5
    assert templates.gallery_version(conn) == 1

    events = outbox.claim_batch(conn, now=T0)
    assert len(events) == 1 and events[0]["type"] == "enrollment.created"
    payload = events[0]["payload"]
    assert payload["patient_code"] == "BN001" and payload["operator_id"] == 7
    assert len(payload["templates"]) == 5
    assert payload["recognizer_sha256"] == SHA
    # embeddings travel base64-encoded, not as raw floats
    import base64
    blob = base64.b64decode(payload["templates"][0]["embedding_b64"])
    np.testing.assert_allclose(templates.decode(blob), vectors[0], atol=1e-6)


def test_commit_makes_the_patient_findable_by_the_matcher(conn, cfg):
    from edgeface.pipeline import matcher

    vectors = [near(unit(5), 0.2, s) for s in range(5)]
    enroll.commit(conn, form(), embeddings_of(vectors), cfg, SHA, now=T0)
    gallery = Gallery(SHA).load(conn, T0)
    probe = embeddings_of([near(unit(5), 0.3, 99)])
    result = matcher.match(probe, gallery, cfg)
    assert result.top1_code == "BN001" and result.top1_score > 0.8


def test_the_face_is_stored_locally_and_never_enters_the_outbox(conn, cfg):
    """The privacy boundary of C-24: the picture stays on this machine.

    Templates are vectors and cannot be turned back into a picture, which is exactly why
    the server is allowed to have them and not allowed to have this.
    """
    import json

    from edgeface.storage import faces

    jpeg = faces.encode(np.full((112, 112, 3), 120, dtype=np.uint8))
    vectors = [near(unit(3), 0.2, s) for s in range(5)]
    enroll.commit(conn, form(), embeddings_of(vectors), cfg, SHA, now=T0, face_jpeg=jpeg)

    assert faces.get(conn, "BN001") == jpeg          # kept here
    events = outbox.claim_batch(conn, now=T0)
    assert events, "the enrolment must still be reported to the server"
    payload = json.dumps([e["payload"] for e in events])
    assert "jpeg" not in payload and "face" not in payload
    assert "\ufffd" not in payload                   # no binary smuggled in as text


def test_the_stored_face_expires_with_the_patient(conn, cfg):
    """C-24 relies on the foreign key, not on a retention branch of its own."""
    from edgeface.storage import faces

    jpeg = faces.encode(np.full((112, 112, 3), 120, dtype=np.uint8))
    vectors = [near(unit(3), 0.2, s) for s in range(5)]
    enroll.commit(conn, form(), embeddings_of(vectors), cfg, SHA, now=T0, face_jpeg=jpeg)

    ttl = cfg["retention"]["patients_hours"] * 3600.0
    with db.transaction(conn):
        patients.delete_expired(conn, T0 + ttl + 1)
    assert faces.count(conn) == 0


def test_an_enrolment_without_a_crop_still_commits(conn, cfg):
    """A capture that never yielded an aligned crop must not block the enrolment."""
    from edgeface.storage import faces

    vectors = [near(unit(3), 0.2, s) for s in range(5)]
    enroll.commit(conn, form(), embeddings_of(vectors), cfg, SHA, now=T0, face_jpeg=None)
    assert patients.get(conn, "BN001") is not None
    assert faces.get(conn, "BN001") is None
