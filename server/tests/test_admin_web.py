# -*- coding: utf-8 -*-
"""Admin web UI: login, CSRF, revocation and the CSV import."""
import datetime as dt
import re

TODAY = dt.date.today().isoformat()


def csrf_from(text):
    match = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return match.group(1) if match else ""


def test_admin_pages_require_login(client):
    for path in ("/admin/", "/admin/patients", "/admin/sessions", "/admin/devices"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/admin/login"


def test_login_with_a_wrong_password(client):
    from server.auth import hash_password
    from server.db import session_scope
    from server.models import Admin

    with session_scope() as session:
        session.merge(Admin(username="admin", password_hash=hash_password("secret123")))
    token = csrf_from(client.get("/admin/login").text)
    response = client.post("/admin/login",
                           data={"username": "admin", "password": "wrong",
                                 "csrf_token": token}, follow_redirects=False)
    assert response.headers["location"] == "/admin/login?error=1"


def test_overview_renders(admin_client):
    page = admin_client.get("/admin/")
    assert page.status_code == 200
    assert "Tổng quan" in page.text


def test_revoke_requires_a_csrf_token(admin_client):
    from server.db import session_scope
    from server.models import Patient

    with session_scope() as session:
        session.merge(Patient(patient_code="BN001", full_name="Nguyễn Thị Hà"))

    without = admin_client.post("/admin/patients/BN001/revoke", data={"reason": "test"})
    assert without.status_code == 400

    with session_scope() as session:
        assert session.get(Patient, "BN001").revoked_at is None   # nothing happened

    token = csrf_from(admin_client.get("/admin/patients").text)
    with_token = admin_client.post("/admin/patients/BN001/revoke",
                                   data={"reason": "test", "csrf_token": token},
                                   follow_redirects=False)
    assert with_token.status_code == 303

    from server.models import Revocation

    with session_scope() as session:
        assert session.get(Patient, "BN001").revoked_at is not None
        assert session.get(Revocation, "BN001").reason == "test"


def test_csv_import_creates_patients_and_appointments(admin_client):
    csv_data = ("patient_code,full_name,birth_year,appointment_code,procedure_date\n"
                "BN001,Nguyễn Thị Hà,1990,AP001,{date}\n"
                "BN002,Trần Văn Bình,1985,AP002,{date}\n").format(date=TODAY)
    token = csrf_from(admin_client.get("/admin/appointments").text)
    response = admin_client.post("/admin/appointments/import",
                                 data={"csrf_token": token},
                                 files={"file": ("today.csv", csv_data, "text/csv")},
                                 follow_redirects=False)
    assert "imported=2" in response.headers["location"]

    from server.db import session_scope
    from server.models import Appointment, GalleryVersion, Patient

    with session_scope() as session:
        assert session.get(Patient, "BN001").full_name == "Nguyễn Thị Hà"
        assert session.get(Appointment, "AP002").procedure_date == TODAY
        assert session.get(GalleryVersion, TODAY).version >= 1


def test_csv_import_rejects_a_bad_file_without_writing_anything(admin_client):
    csv_data = ("patient_code,full_name,birth_year,appointment_code,procedure_date\n"
                "BN001,Nguyễn Thị Hà,not-a-year,AP001,{date}\n").format(date=TODAY)
    token = csrf_from(admin_client.get("/admin/appointments").text)
    response = admin_client.post("/admin/appointments/import",
                                 data={"csrf_token": token},
                                 files={"file": ("bad.csv", csv_data, "text/csv")},
                                 follow_redirects=False)
    assert "error=" in response.headers["location"]

    from server.db import session_scope
    from server.models import Patient

    with session_scope() as session:
        assert session.get(Patient, "BN001") is None


def test_missing_csv_columns_are_reported(admin_client):
    token = csrf_from(admin_client.get("/admin/appointments").text)
    response = admin_client.post("/admin/appointments/import",
                                 data={"csrf_token": token},
                                 files={"file": ("bad.csv", "a,b\n1,2\n", "text/csv")},
                                 follow_redirects=False)
    assert "missing%20columns" in response.headers["location"] or \
           "missing columns" in response.headers["location"]


def test_creating_a_device_shows_the_token_once(admin_client):
    token = csrf_from(admin_client.get("/admin/devices").text)
    response = admin_client.post("/admin/devices",
                                 data={"device_id": "kiosk-02", "name": "Kiosk 2",
                                       "csrf_token": token}, follow_redirects=False)
    location = response.headers["location"]
    assert location.startswith("/admin/devices?token=")
    device_token = location.split("token=")[1]

    from server.db import hash_token, session_scope
    from server.models import Device

    with session_scope() as session:
        device = session.get(Device, "kiosk-02")
        assert device.token_hash == hash_token(device_token)   # only the hash is stored
        assert device_token not in device.token_hash


def test_sessions_csv_export(admin_client):
    from server.db import session_scope
    from server.models import SessionLog

    with session_scope() as session:
        session.merge(SessionLog(session_id="sess-1", device_id="kiosk-01", kind="identify",
                                 started_at=dt.datetime.now(dt.timezone.utc),
                                 decision="review_required", rule_id="R3",
                                 top1_code="BN001", top1_score=0.9, votes=5,
                                 nurse_action="confirm", confirmed_code="BN001"))
    response = admin_client.get("/admin/sessions.csv?days=7")
    assert response.status_code == 200
    assert "sess-1" in response.text and "review_required" in response.text
    assert response.headers["content-disposition"].endswith("sessions.csv")
