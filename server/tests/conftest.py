import os
import tempfile

import pytest

TEMP_DIR = tempfile.mkdtemp(prefix="edgeface-server-tests-")
os.environ.setdefault("EDGEFACE_DB", "sqlite:///" + os.path.join(TEMP_DIR, "test.db"))
os.environ.setdefault("EDGEFACE_SECRET", "test-secret-key")
os.environ.setdefault("EDGEFACE_BUNDLES", os.path.join(TEMP_DIR, "bundles"))
os.environ.setdefault("EDGEFACE_BUNDLE_KEY", os.path.join(TEMP_DIR, "bundle.key"))


@pytest.fixture
def client():
    """A fresh database per test: SQLite file dropped and the schema recreated."""
    from fastapi.testclient import TestClient

    from server import db as server_db
    from server.app import create_app
    from server.models import Base

    Base.metadata.drop_all(server_db.engine)
    Base.metadata.create_all(server_db.engine)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def device_token(client):
    from server.db import hash_token, session_scope
    from server.models import Device

    token = "test-device-token"
    with session_scope() as session:
        session.merge(Device(device_id="kiosk-01", name="Kiosk", token_hash=hash_token(token)))
    return token


@pytest.fixture
def auth(device_token):
    return {"Authorization": "Bearer " + device_token}


@pytest.fixture
def admin_client(client):
    """A logged-in admin session, with the CSRF token of the current page."""
    from server.auth import hash_password
    from server.db import session_scope
    from server.models import Admin

    with session_scope() as session:
        session.merge(Admin(username="admin", password_hash=hash_password("secret123")))
    client.get("/admin/login")
    token = _csrf_of(client)
    response = client.post("/admin/login",
                           data={"username": "admin", "password": "secret123",
                                 "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    return client


def _csrf_of(client):
    import re

    page = client.get("/admin/login").text
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    return match.group(1) if match else ""


def csrf(client):
    return _csrf_of(client)
