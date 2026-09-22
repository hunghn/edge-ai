# -*- coding: utf-8 -*-
"""GET /api/v1/gallery and friends: what the kiosk is allowed to pull."""
import base64
import datetime as dt

import numpy as np

TODAY = dt.date.today().isoformat()
TOMORROW = (dt.date.today() + dt.timedelta(days=1)).isoformat()
SHA = "sha-mbf"


def seed(patient_code="BN001", date=TODAY, sha=SHA, templates=2):
    from server.db import bump_gallery_version, session_scope
    from server.models import Appointment, FaceTemplate, Patient

    rng = np.random.RandomState(abs(hash(patient_code)) % 1000)
    with session_scope() as session:
        session.merge(Patient(patient_code=patient_code, full_name="BN " + patient_code,
                              birth_year=1990))
        session.merge(Appointment(appointment_code="AP-" + patient_code,
                                  patient_code=patient_code, procedure_date=date))
        for _ in range(templates):
            vector = rng.randn(512).astype("<f4")
            vector /= np.linalg.norm(vector)
            session.add(FaceTemplate(patient_code=patient_code, embedding=vector.tobytes(),
                                     quality=0.9, recognizer_sha256=sha))
        bump_gallery_version(session, date)


def test_gallery_needs_a_token(client):
    assert client.get("/api/v1/gallery").status_code == 401


def test_gallery_returns_todays_patients_with_templates(client, auth):
    seed("BN001")
    seed("BN002", date=TOMORROW)
    body = client.get("/api/v1/gallery", headers=auth).json()

    assert body["changed"] is True and body["date"] == TODAY
    assert [p["patient_code"] for p in body["patients"]] == ["BN001"]
    template = body["patients"][0]["templates"][0]
    assert len(base64.b64decode(template["embedding_b64"])) == 512 * 4
    assert body["patients"][0]["appointment_code"] == "AP-BN001"


def test_unchanged_gallery_is_not_resent(client, auth):
    """Saves the device a download on every poll (D-26 is a few minutes)."""
    seed("BN001")
    version = client.get("/api/v1/gallery", headers=auth).json()["version"]
    again = client.get("/api/v1/gallery", headers=auth,
                       params={"since_version": version}).json()
    assert again["changed"] is False and again["patients"] == []

    seed("BN003")     # new patient -> version moves -> full payload again
    after = client.get("/api/v1/gallery", headers=auth,
                       params={"since_version": version}).json()
    assert after["changed"] is True and after["version"] > version
    assert len(after["patients"]) == 2


def test_revoked_patients_are_excluded(client, auth):
    seed("BN001")
    seed("BN002")
    from server.db import session_scope
    from server.models import Patient

    with session_scope() as session:
        session.get(Patient, "BN002").revoked_at = dt.datetime.now(dt.timezone.utc)

    body = client.get("/api/v1/gallery", headers=auth).json()
    assert [p["patient_code"] for p in body["patients"]] == ["BN001"]


def test_templates_are_filtered_by_recognizer(client, auth):
    """Embeddings from another model are not comparable, so they must not be sent."""
    seed("BN001", sha=SHA)
    seed("BN002", sha="sha-other")
    body = client.get("/api/v1/gallery", headers=auth,
                      params={"recognizer_sha256": SHA}).json()
    assert [p["patient_code"] for p in body["patients"]] == ["BN001"]


def test_a_patient_without_templates_is_skipped(client, auth):
    from server.db import bump_gallery_version, session_scope
    from server.models import Appointment, Patient

    with session_scope() as session:
        session.merge(Patient(patient_code="BN009", full_name="Chưa đăng ký mặt"))
        session.merge(Appointment(appointment_code="AP-BN009", patient_code="BN009",
                                  procedure_date=TODAY))
        bump_gallery_version(session, TODAY)
    assert client.get("/api/v1/gallery", headers=auth).json()["patients"] == []


def test_revocation_list(client, auth):
    from server.db import session_scope
    from server.models import Revocation

    with session_scope() as session:
        session.merge(Revocation(patient_code="BN005", reason="nurse"))
    rows = client.get("/api/v1/revocations", headers=auth).json()
    assert [row["patient_code"] for row in rows] == ["BN005"]

    future = dt.datetime.now(dt.timezone.utc).timestamp() + 60
    assert client.get("/api/v1/revocations", headers=auth,
                      params={"since": future}).json() == []


def test_bundle_download_and_signature(client, auth, tmp_path):
    import hashlib

    from server.api.gallery import sign_bundle
    from server.cli import read_or_create_key
    from server.db import session_scope
    from server.models import Bundle
    from server.settings import settings

    assert client.get("/api/v1/bundles/latest", headers=auth).status_code == 404

    path = tmp_path / "bundle.tar"
    path.write_bytes(b"model-bundle-contents")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    key = read_or_create_key(settings.bundle_key_path)
    with session_scope() as session:
        session.merge(Bundle(version="2026-09-22", file_path=str(path), sha256=digest,
                             signature=sign_bundle(digest, "2026-09-22", key),
                             size=path.stat().st_size, active=True))

    meta = client.get("/api/v1/bundles/latest", headers=auth).json()
    assert meta["sha256"] == digest
    assert meta["signature"] == sign_bundle(digest, "2026-09-22", key)

    downloaded = client.get(meta["url"], headers=auth)
    assert downloaded.status_code == 200
    assert hashlib.sha256(downloaded.content).hexdigest() == digest
