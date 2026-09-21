import pytest

from edgeface.storage import db, patients, templates
from edgeface.storage.patients import strip_accents

HOUR = 3600.0
T0 = 1_700_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def add(conn, code, name, at=T0, source="kiosk", ttl_hours=24, birth_year=1990):
    with db.transaction(conn):
        return patients.upsert_patient(conn, code, name, birth_year, source, at, ttl_hours)


def test_strip_accents_vietnamese():
    assert strip_accents("Nguyễn Thị Hà") == "nguyen thi ha"
    assert strip_accents("ĐẶNG VĂN Đủ") == "dang van du"
    assert strip_accents(None) == ""


def test_insert_then_update_keeps_templates(conn):
    assert add(conn, "BN001", "Nguyễn Thị Hà") == "inserted"
    with db.transaction(conn):
        templates.add_templates(conn, "BN001", [[0.1] * 512], "sha-abc")
    assert add(conn, "BN001", "Nguyễn Thị Hằng") == "updated"
    # an UPDATE must not cascade the templates away (INSERT OR REPLACE would have)
    assert templates.count(conn, "BN001") == 1
    assert patients.get(conn, "BN001")["full_name"] == "Nguyễn Thị Hằng"
    assert patients.get(conn, "BN001")["name_search"] == "nguyen thi hang"


def test_search_ignores_accents_and_case(conn):
    add(conn, "BN001", "Nguyễn Thị Hà")
    add(conn, "BN002", "Trần Văn Bình")
    assert [p["patient_code"] for p in patients.search(conn, "nguyen", now=T0)] == ["BN001"]
    assert [p["patient_code"] for p in patients.search(conn, "Thị Hà", now=T0)] == ["BN001"]
    assert [p["patient_code"] for p in patients.search(conn, "bn00", now=T0)] == ["BN001", "BN002"]
    assert patients.search(conn, "khong-co", now=T0) == []


def test_search_and_list_exclude_expired_and_revoked(conn):
    add(conn, "BN001", "A")
    add(conn, "BN002", "B")
    with db.transaction(conn):
        patients.revoke(conn, "BN002", "test", T0 + 60)
    assert [p["patient_code"] for p in patients.list_active(conn, now=T0 + 120)] == ["BN001"]
    assert patients.search(conn, "BN002", now=T0 + 120) == []   # revoked -> not searchable
    # after the TTL nothing is active any more
    assert patients.list_active(conn, now=T0 + 25 * HOUR) == []
    assert patients.count_active(conn, T0 + 25 * HOUR) == 0


def test_delete_expired_and_apply_revocations(conn):
    add(conn, "BN001", "A", at=T0)
    add(conn, "BN002", "B", at=T0 + 12 * HOUR)
    with db.transaction(conn):
        assert patients.delete_expired(conn, T0 + 25 * HOUR) == 1      # only BN001 is past TTL
    assert patients.get(conn, "BN001") is None
    assert patients.get(conn, "BN002") is not None

    with db.transaction(conn):
        patients.revoke(conn, "BN002", "server said so", T0 + 13 * HOUR)
    with db.transaction(conn):
        assert patients.apply_revocations(conn) == 1
    assert patients.get(conn, "BN002") is None


def test_appointments_and_lookup_for_date(conn):
    add(conn, "BN001", "Nguyễn Thị Hà")
    with db.transaction(conn):
        patients.upsert_appointment(conn, "AP1", "BN001", "2026-09-21")
        assert patients.upsert_appointment(conn, "AP1", "BN001", "2026-09-22") == "updated"
    rows = patients.list_for_date(conn, "2026-09-22", now=T0)
    assert [r["patient_code"] for r in rows] == ["BN001"]
    assert rows[0]["appointment_code"] == "AP1"
    assert patients.list_for_date(conn, "2026-09-21", now=T0) == []
    card = patients.get_with_appointment(conn, "BN001", "2026-09-22")
    assert card["appointment_code"] == "AP1" and card["full_name"] == "Nguyễn Thị Hà"


def test_revoke_records_revocation_row(conn):
    add(conn, "BN001", "A")
    with db.transaction(conn):
        patients.revoke(conn, "BN001", "nurse", T0 + 5)
        patients.revoke(conn, "BN001", "again", T0 + 6)   # second revoke updates, not duplicates
    rows = conn.execute("SELECT * FROM revocations").fetchall()
    assert len(rows) == 1 and rows[0]["reason"] == "again"
