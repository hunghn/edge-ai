# -*- coding: utf-8 -*-
"""Sync: uploading, pulling and bundle verification, against a stub server.

The stub lets the tests do what a real server cannot on demand: disappear mid-upload,
reject one event, or hand back a tampered model bundle.
"""
import base64
import os

import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.storage import db, outbox, patients, templates
from edgeface.sync import puller, uploader
from edgeface.sync.bundle import BundleError, expected_signature, sync_bundle
from edgeface.sync.client import ServerError

T0 = 1_700_000_000.0
SHA = "sha-mbf"


@pytest.fixture
def cfg(repo_root):
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def vector(seed):
    rng = np.random.RandomState(seed)
    v = rng.randn(512).astype("<f4")
    return (v / np.linalg.norm(v)).astype("<f4")


class StubServer(object):
    """A server that can be told to fail, reject or return whatever the test needs."""

    def __init__(self):
        self.received = []
        self.fail_with = None
        self.reject_ids = set()
        self.gallery_payload = {"changed": False}
        self.revocations = []
        self.bundle_meta = None
        self.bundle_bytes = b""
        self.heartbeats = []

    def post_events(self, events):
        if self.fail_with:
            raise ServerError(self.fail_with)
        accepted, duplicate, rejected = [], [], []
        known = {e["event_id"] for e in self.received}
        for event in events:
            if event["event_id"] in self.reject_ids:
                rejected.append({"event_id": event["event_id"], "error": "bad payload"})
            elif event["event_id"] in known:
                duplicate.append(event["event_id"])
            else:
                self.received.append(event)
                accepted.append(event["event_id"])
        return {"accepted": accepted, "duplicate": duplicate, "rejected": rejected}

    def get_gallery(self, date=None, since_version=0, recognizer_sha256=None):
        if self.fail_with:
            raise ServerError(self.fail_with)
        return self.gallery_payload

    def get_revocations(self, since=0.0):
        if self.fail_with:
            raise ServerError(self.fail_with)
        return [row for row in self.revocations if row["revoked_at"] > since]

    def get_latest_bundle(self):
        return self.bundle_meta

    def download(self, path, destination):
        with open(destination, "wb") as f:
            f.write(self.bundle_bytes)
        return destination

    def heartbeat(self, **fields):
        self.heartbeats.append(fields)
        return {"ok": True}

    def close(self):
        pass


def queue(conn, count=3, at=T0):
    ids = []
    with db.transaction(conn):
        for i in range(count):
            ids.append(outbox.enqueue(conn, "session.closed", {"session_id": "s%d" % i}, at))
    return ids


# ---------------------------------------------------------------- upload
def test_events_are_sent_and_marked(conn):
    server = StubServer()
    queue(conn, 3)
    result = uploader.upload_once(conn, server, now=T0)
    assert result["sent"] == 3 and result["pending"] == 0
    assert len(server.received) == 3


def test_network_failure_keeps_everything_queued(conn):
    """Offline-first: nothing is lost, and each event backs off before the next try."""
    server = StubServer()
    server.fail_with = "connection refused"
    queue(conn, 3)
    result = uploader.upload_once(conn, server, now=T0)
    assert result["sent"] == 0 and result["error"] == "connection refused"
    assert outbox.pending_count(conn) == 3
    assert outbox.claim_batch(conn, now=T0) == []          # not due yet, they backed off

    server.fail_with = None
    later = uploader.upload_once(conn, server, now=T0 + 60)
    assert later["sent"] == 3 and outbox.pending_count(conn) == 0


def test_a_duplicate_counts_as_delivered(conn):
    """The server already has it; keeping it queued forever would be wrong."""
    server = StubServer()
    ids = queue(conn, 2)
    uploader.upload_once(conn, server, now=T0)
    with db.transaction(conn):
        conn.execute("UPDATE outbox SET sent_at = NULL, next_attempt_at = ? WHERE event_id IN "
                     "(?, ?)", (T0, ids[0], ids[1]))
    result = uploader.upload_once(conn, server, now=T0 + 1)
    assert result["duplicate"] == 2 and outbox.pending_count(conn) == 0


def test_a_rejected_event_is_kept_and_reported(conn):
    server = StubServer()
    ids = queue(conn, 2)
    server.reject_ids = {ids[0]}
    result = uploader.upload_once(conn, server, now=T0)
    assert result["sent"] == 1 and result["rejected"] == 1
    assert outbox.pending_count(conn) == 1                 # kept, never silently dropped
    row = db.read_one(conn, "SELECT last_error, attempts FROM outbox WHERE event_id = ?",
                      (ids[0],))
    assert row["attempts"] == 1 and "bad payload" in row["last_error"]


def test_drain_empties_the_queue_in_batches(conn):
    server = StubServer()
    queue(conn, 12)
    totals = uploader.drain(conn, server, batch_size=5, now=T0)
    # 5 + 5 + 2, plus one more poll that comes back empty and ends the loop.
    assert totals["sent"] == 12 and totals["batches"] == 4
    assert outbox.pending_count(conn) == 0


# ---------------------------------------------------------------- pull
def gallery_payload(codes, date="2026-09-22", version=3):
    return {"changed": True, "date": date, "version": version,
            "recognizer_sha256": SHA,
            "patients": [{"patient_code": code, "full_name": "BN " + code,
                          "birth_year": 1990, "appointment_code": "AP-" + code,
                          "templates": [{"embedding_b64": base64.b64encode(
                              vector(i).tobytes()).decode(), "quality": 0.9}]}
                         for i, code in enumerate(codes)]}


def test_gallery_pull_writes_patients_and_templates(conn, cfg):
    server = StubServer()
    server.gallery_payload = gallery_payload(["BN001", "BN002"])
    result = puller.pull_once(conn, server, SHA, now=T0)
    assert result["patients"] == 2
    assert templates.count(conn) == 2
    assert patients.get(conn, "BN001")["source"] == "server"
    codes, matrix, _ = templates.load_gallery(conn, SHA, now=T0)
    assert codes == ["BN001", "BN002"] and matrix.shape == (2, 512)


def test_patients_dropped_from_the_list_are_removed(conn):
    server = StubServer()
    server.gallery_payload = gallery_payload(["BN001", "BN002"])
    puller.pull_once(conn, server, SHA, now=T0)
    server.gallery_payload = gallery_payload(["BN001"], version=4)
    puller.pull_once(conn, server, SHA, now=T0 + 10)
    assert patients.get(conn, "BN002") is None and patients.get(conn, "BN001") is not None


def test_a_kiosk_enrollment_survives_a_gallery_pull(conn):
    """The server may not know about it yet: the outbox may still be queued."""
    with db.transaction(conn):
        patients.upsert_patient(conn, "BN_LOCAL", "Nguyễn Thị Hà", 1990, "kiosk", T0)
        templates.add_templates(conn, "BN_LOCAL", [vector(9)], SHA, created_at=T0)
    server = StubServer()
    server.gallery_payload = gallery_payload(["BN001"])
    puller.pull_once(conn, server, SHA, now=T0)
    assert patients.get(conn, "BN_LOCAL") is not None
    assert templates.count(conn, "BN_LOCAL") == 1


def test_revocation_deletes_even_a_local_enrollment(conn):
    with db.transaction(conn):
        patients.upsert_patient(conn, "BN_LOCAL", "A", 1990, "kiosk", T0)
        templates.add_templates(conn, "BN_LOCAL", [vector(3)], SHA, created_at=T0)
    server = StubServer()
    server.revocations = [{"patient_code": "BN_LOCAL", "revoked_at": T0 + 5,
                           "reason": "server"}]
    result = puller.pull_once(conn, server, SHA, now=T0 + 10)
    assert result["revoked"] == 1
    assert patients.get(conn, "BN_LOCAL") is None and templates.count(conn) == 0


def test_unchanged_gallery_does_nothing(conn):
    server = StubServer()
    server.gallery_payload = {"changed": False}
    before = templates.gallery_version(conn)
    result = puller.pull_once(conn, server, SHA, now=T0)
    assert result["changed"] is False
    assert templates.gallery_version(conn) == before


# ---------------------------------------------------------------- bundles
def make_bundle(tmp_path, with_manifest=True, corrupt_file=False):
    import hashlib
    import tarfile

    staging = tmp_path / "src"
    staging.mkdir()
    model = staging / "det_500m.onnx"
    model.write_bytes(b"onnx-model-bytes")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if corrupt_file:
        model.write_bytes(b"tampered-model-bytes")
    if with_manifest:
        (staging / "manifest.yaml").write_text(
            "det_500m:\n  file: det_500m.onnx\n  sha256: {}\n".format(digest))
    archive = tmp_path / "bundle.tar"
    with tarfile.open(str(archive), "w") as tar:
        for item in staging.iterdir():
            tar.add(str(item), arcname=item.name)
    return archive


@pytest.fixture
def bundle_key(tmp_path):
    path = tmp_path / "bundle.key"
    path.write_bytes(b"0123456789abcdef")
    return str(path)


def offer(server, archive, version="2026-09-22", key=b"0123456789abcdef", sha=None):
    import hashlib

    data = archive.read_bytes()
    digest = sha or hashlib.sha256(data).hexdigest()
    server.bundle_bytes = data
    server.bundle_meta = {"version": version, "sha256": digest,
                          "signature": expected_signature(digest, version, key),
                          "url": "/api/v1/bundles/{}/file".format(version)}
    return server.bundle_meta


def test_a_good_bundle_is_staged(conn, tmp_path, bundle_key):
    from edgeface.storage import models_registry

    server = StubServer()
    offer(server, make_bundle(tmp_path))
    result = sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)
    assert result["status"] == "staged" and result["files"] == 1
    row = models_registry.get(conn, "2026-09-22")
    assert row["status"] == "staged"          # staged, not active: the engine swaps on restart
    assert os.path.isfile(os.path.join(result["path"], "det_500m.onnx"))


def test_a_wrong_sha256_is_refused(conn, tmp_path, bundle_key):
    from edgeface.storage import models_registry

    server = StubServer()
    offer(server, make_bundle(tmp_path), sha="0" * 64)
    with pytest.raises(BundleError) as excinfo:
        sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)
    assert "sha256 mismatch" in str(excinfo.value)
    assert models_registry.get(conn, "2026-09-22")["status"] == "rejected"


def test_a_wrong_signature_is_refused(conn, tmp_path, bundle_key):
    server = StubServer()
    offer(server, make_bundle(tmp_path), key=b"the-wrong-key")
    with pytest.raises(BundleError) as excinfo:
        sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)
    assert "signature mismatch" in str(excinfo.value)


def test_a_file_that_does_not_match_the_manifest_is_refused(conn, tmp_path, bundle_key):
    """The archive is intact and signed, but a model inside was swapped."""
    server = StubServer()
    offer(server, make_bundle(tmp_path, corrupt_file=True))
    with pytest.raises(BundleError) as excinfo:
        sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)
    assert "sha256 mismatch" in str(excinfo.value)


def test_a_bundle_without_a_manifest_is_refused(conn, tmp_path, bundle_key):
    server = StubServer()
    offer(server, make_bundle(tmp_path, with_manifest=False))
    with pytest.raises(BundleError):
        sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)


def test_the_same_bundle_is_not_downloaded_twice(conn, tmp_path, bundle_key):
    server = StubServer()
    offer(server, make_bundle(tmp_path))
    sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0)
    again = sync_bundle(conn, server, str(tmp_path / "bundles"), bundle_key, now=T0 + 1)
    assert again["changed"] is False and "already have" in again["reason"]
