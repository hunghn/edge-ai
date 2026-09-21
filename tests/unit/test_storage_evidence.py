import hashlib
import os

import pytest

from edgeface.storage import db, evidence, sessions

T0 = 1_700_000_000.0
JPEG = b"\xff\xd8\xff\xe0not-a-real-jpeg\xff\xd9"


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


@pytest.fixture
def evidence_dir(tmp_path):
    return str(tmp_path / "evidence")


def save(conn, evidence_dir, session_id=None, at=T0, ttl_days=7):
    with db.transaction(conn):
        return evidence.save(conn, session_id, JPEG, evidence_dir, ttl_days=ttl_days, at=at)


def test_save_writes_file_and_row(conn, evidence_dir):
    row = save(conn, evidence_dir)
    assert os.path.isfile(row["path"])
    with open(row["path"], "rb") as f:
        assert f.read() == JPEG
    assert row["sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert row["expires_at"] == T0 + 7 * 86400.0
    assert not [n for n in os.listdir(evidence_dir) if n.endswith(".tmp")]  # atomic rename


def test_linked_to_session_and_survives_its_deletion(conn, evidence_dir):
    with db.transaction(conn):
        sid = sessions.open_session(conn, sessions.KIND_IDENTIFY, T0, ttl_days=1)
    save(conn, evidence_dir, session_id=sid)
    assert len(evidence.get_for_session(conn, sid)) == 1
    with db.transaction(conn):
        sessions.purge_expired(conn, T0 + 2 * 86400.0)
    # ON DELETE SET NULL: the image stays until its own TTL, without a dangling reference
    assert evidence.count(conn) == 1
    assert conn.execute("SELECT session_id FROM evidence").fetchone()["session_id"] is None


def test_purge_expired_deletes_files_and_rows(conn, evidence_dir):
    old = save(conn, evidence_dir, at=T0, ttl_days=7)
    new = save(conn, evidence_dir, at=T0 + 6 * 86400.0, ttl_days=7)
    with db.transaction(conn):
        files, rows = evidence.purge_expired(conn, now=T0 + 8 * 86400.0)
    assert (files, rows) == (1, 1)
    assert not os.path.exists(old["path"]) and os.path.exists(new["path"])


def test_purge_expired_tolerates_a_missing_file(conn, evidence_dir):
    row = save(conn, evidence_dir)
    os.remove(row["path"])
    with db.transaction(conn):
        files, rows = evidence.purge_expired(conn, now=T0 + 8 * 86400.0)
    assert (files, rows) == (0, 1)      # row still goes away
    assert evidence.count(conn) == 0


def test_purge_orphans_removes_crash_leftovers(conn, evidence_dir):
    kept = save(conn, evidence_dir)
    os.makedirs(evidence_dir, exist_ok=True)
    orphan = os.path.join(evidence_dir, "deadbeef.jpg")
    leftover_tmp = os.path.join(evidence_dir, "deadbeef.jpg.tmp")
    for path in (orphan, leftover_tmp):
        with open(path, "wb") as f:
            f.write(JPEG)
    assert evidence.purge_orphans(conn, evidence_dir) == 2
    assert os.path.exists(kept["path"])
