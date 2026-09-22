# -*- coding: utf-8 -*-
"""Device and server together: a real uvicorn process, the real sync client.

Covers the loop the clinic actually depends on: a patient enrolled at the kiosk reaches
the server, comes back in tomorrow's gallery, and disappears everywhere once revoked.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytestmark = pytest.mark.integration


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(url, timeout=30.0):
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def server():
    """A real server process, with its own database and bundle key."""
    workdir = tempfile.mkdtemp(prefix="edgeface-e2e-")
    port = free_port()
    env = dict(os.environ,
               EDGEFACE_DB="sqlite:///" + os.path.join(workdir, "server.db"),
               EDGEFACE_SECRET="integration-secret",
               EDGEFACE_BUNDLES=os.path.join(workdir, "bundles"),
               EDGEFACE_BUNDLE_KEY=os.path.join(workdir, "bundle.key"),
               PYTHONPATH=REPO)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.app:app", "--port", str(port),
         "--log-level", "warning"],
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base_url = "http://127.0.0.1:{}".format(port)
    if not wait_for(base_url + "/healthz"):
        process.kill()
        pytest.fail("server did not start: " + process.stdout.read().decode()[-2000:])

    token = "integration-device-token"
    subprocess.check_call(
        [sys.executable, "-c",
         "from server.db import hash_token, session_scope, create_all;"
         "from server.models import Device;"
         "create_all();"
         "session = session_scope();"
         "s = session.__enter__();"
         "s.merge(Device(device_id='kiosk-01', name='Kiosk', "
         "token_hash=hash_token('{}')));"
         "session.__exit__(None, None, None)".format(token)],
        cwd=REPO, env=env)
    yield {"url": base_url, "token": token, "env": env, "workdir": workdir}
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture
def device(tmp_path, server):
    """A device database plus a sync client pointed at the server."""
    from edgeface.storage import db
    from edgeface.sync.client import ServerClient

    conn = db.open_db(str(tmp_path / "edge.db"))
    client = ServerClient(server["url"], server["token"], "kiosk-01")
    yield conn, client
    client.close()
    conn.close()


def vector(seed):
    rng = np.random.RandomState(seed)
    v = rng.randn(512).astype("<f4")
    return (v / np.linalg.norm(v)).astype("<f4")


def test_enrollment_reaches_the_server_and_comes_back_in_the_gallery(device, server):
    import datetime as dt

    from edgeface import config as cfg_mod
    from edgeface.engine import enroll
    from edgeface.storage import db, outbox, patients, templates
    from edgeface.sync import puller, uploader
    from edgeface.types import Embedding

    conn, client = device
    cfg = cfg_mod.load_config(os.path.join(REPO, "configs", "dev.yaml"))
    today = dt.date.today().isoformat()

    # 1. The kiosk enrolls a patient.
    embeddings = [Embedding(i, float(i), vector(i), 0.9, 21.0) for i in range(5)]
    enroll.commit(conn, {"patient_code": "BN777", "full_name": "Nguyễn Thị Hà",
                         "birth_year": 1990, "appointment_code": "AP777",
                         "procedure_date": today},
                  embeddings, cfg, "sha-mbf")
    assert outbox.pending_count(conn) == 1

    # 2. Sync pushes it.
    totals = uploader.drain(conn, client)
    assert totals["sent"] == 1 and totals["error"] is None
    assert outbox.pending_count(conn) == 0

    # 3. A second device pulls the same day and receives that patient.
    other_db = db.open_db(os.path.join(os.path.dirname(conn.execute(
        "PRAGMA database_list").fetchone()[2]), "other.db"))
    try:
        result = puller.pull_once(other_db, client, "sha-mbf", date=today)
        assert result["patients"] == 1
        assert patients.get(other_db, "BN777")["full_name"] == "Nguyễn Thị Hà"
        assert templates.count(other_db, "BN777") == 5
        codes, matrix, _ = templates.load_gallery(other_db, "sha-mbf")
        assert codes == ["BN777"] and matrix.shape == (5, 512)
        np.testing.assert_allclose(matrix[0], vector(0), atol=1e-6)
    finally:
        other_db.close()


def test_revoking_on_the_server_removes_the_patient_from_the_device(device, server):
    import datetime as dt

    from edgeface import config as cfg_mod
    from edgeface.engine import enroll
    from edgeface.storage import patients, templates
    from edgeface.sync import puller, uploader
    from edgeface.types import Embedding

    conn, client = device
    cfg = cfg_mod.load_config(os.path.join(REPO, "configs", "dev.yaml"))
    today = dt.date.today().isoformat()
    enroll.commit(conn, {"patient_code": "BN888", "full_name": "Trần Văn Bình",
                         "appointment_code": "AP888", "procedure_date": today},
                  [Embedding(i, float(i), vector(20 + i), 0.9, 21.0) for i in range(3)],
                  cfg, "sha-mbf")
    uploader.drain(conn, client)

    # The admin revokes on the server.
    subprocess.check_call(
        [sys.executable, "-c",
         "import datetime as dt;"
         "from server.db import session_scope, create_all;"
         "from server.models import Patient, Revocation;"
         "create_all();"
         "ctx = session_scope(); s = ctx.__enter__();"
         "p = s.get(Patient, 'BN888');"
         "p.revoked_at = dt.datetime.now(dt.timezone.utc);"
         "s.merge(Revocation(patient_code='BN888', reason='admin'));"
         "ctx.__exit__(None, None, None)"],
        cwd=REPO, env=server["env"])

    assert patients.get(conn, "BN888") is not None      # still on the device before the pull
    result = puller.pull_once(conn, client, "sha-mbf", date=today)
    assert result["revoked"] == 1
    assert patients.get(conn, "BN888") is None
    assert templates.count(conn, "BN888") == 0


def test_the_device_survives_the_server_going_away(device, server):
    """Offline-first: the queue grows, nothing is lost, and it drains when it returns."""
    from edgeface.storage import db, outbox
    from edgeface.sync import uploader
    from edgeface.sync.client import ServerClient

    conn, client = device
    dead = ServerClient("http://127.0.0.1:1", server["token"], "kiosk-01")
    with db.transaction(conn):
        for i in range(4):
            outbox.enqueue(conn, "session.closed", {"session_id": "offline-%d" % i})

    failed = uploader.upload_once(conn, dead, now=time.time())
    assert failed["sent"] == 0 and failed["error"] is not None
    assert outbox.pending_count(conn) == 4

    # Backoff has pushed them into the future; a later run sends them all.
    totals = uploader.drain(conn, client, now=time.time() + 600)
    assert totals["sent"] == 4 and outbox.pending_count(conn) == 0
    dead.close()


def test_heartbeat_updates_the_fleet_view(device):
    from edgeface.sync.__main__ import SyncService

    conn, client = device
    from edgeface import config as cfg_mod

    cfg = cfg_mod.load_config(os.path.join(REPO, "configs", "dev.yaml"))
    service = SyncService.__new__(SyncService)     # no database reopening
    service.conn = conn
    service.client = client
    service.cfg = cfg
    service.sync_cfg = dict(cfg["sync"])
    assert service.heartbeat()["ok"] is True
