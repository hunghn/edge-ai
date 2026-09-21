import sqlite3

import pytest

from edgeface.storage import clock, db


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def test_pragmas_are_set(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000


def test_migrate_is_idempotent(tmp_path):
    path = str(tmp_path / "edge.db")
    first = db.connect(path)
    assert db.migrate(first) == [1]
    assert db.migrate(first) == []          # nothing pending the second time
    assert db.schema_version(first) == 1
    first.close()
    second = db.open_db(path)               # a second process opening it changes nothing
    assert db.schema_version(second) == 1
    second.close()


def test_singleton_rows_created_by_migration(conn):
    assert conn.execute("SELECT COUNT(*) FROM kiosk_state").fetchone()[0] == 1
    assert db.get_meta(conn, "version") == "0"


def test_transaction_commits_and_rolls_back(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO revocations (patient_code, revoked_at) VALUES ('P1', 1.0)")
    assert conn.execute("SELECT COUNT(*) FROM revocations").fetchone()[0] == 1

    with pytest.raises(RuntimeError):
        with db.transaction(conn):
            conn.execute("INSERT INTO revocations (patient_code, revoked_at) VALUES ('P2', 1.0)")
            raise RuntimeError("boom")
    assert conn.execute("SELECT COUNT(*) FROM revocations").fetchone()[0] == 1
    # the connection is usable afterwards
    with db.transaction(conn):
        conn.execute("DELETE FROM revocations")


def test_transaction_retries_while_the_write_lock_is_held(tmp_path):
    path = str(tmp_path / "edge.db")
    holder = db.open_db(path)
    other = db.connect(path, timeout_s=0.05)
    holder.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError):
        with db.transaction(other, retries=1, base_delay_s=0.001):
            pass
    holder.execute("COMMIT")
    with db.transaction(other, retries=1, base_delay_s=0.001):   # lock free again
        other.execute("INSERT INTO revocations (patient_code, revoked_at) VALUES ('P1', 1.0)")
    assert other.execute("SELECT COUNT(*) FROM revocations").fetchone()[0] == 1
    holder.close()
    other.close()


def test_foreign_keys_cascade(conn):
    with db.transaction(conn):
        conn.execute("INSERT INTO patients (patient_code, full_name, name_search, source, "
                     "created_at, expires_at) VALUES ('P1', 'A', 'a', 'kiosk', 0, 1e12)")
        conn.execute("INSERT INTO face_templates (patient_code, embedding, recognizer_sha256, "
                     "created_at) VALUES ('P1', X'00', 'sha', 0)")
        conn.execute("INSERT INTO appointments (appointment_code, patient_code, procedure_date) "
                     "VALUES ('A1', 'P1', '2026-01-01')")
    with db.transaction(conn):
        conn.execute("DELETE FROM patients WHERE patient_code = 'P1'")
    assert conn.execute("SELECT COUNT(*) FROM face_templates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM appointments").fetchone()[0] == 0


def test_meta_helpers(conn):
    db.set_meta(conn, "some_key", 42)
    assert db.get_meta(conn, "some_key") == "42"
    db.set_meta(conn, "some_key", 43)
    assert db.get_meta(conn, "some_key") == "43"
    assert db.get_meta(conn, "missing", "fallback") == "fallback"


def test_clock_can_be_faked():
    previous = clock.set_clock(lambda: 1234.5)
    try:
        assert clock.now() == 1234.5
    finally:
        clock.set_clock(previous)
    assert clock.now() > 1e9
