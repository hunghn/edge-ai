import pytest

from edgeface.storage import db, operators

T0 = 1_700_000_000.0
FAST = 1000          # PBKDF2 rounds: keep tests quick, production uses auth.pbkdf2_iterations


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


@pytest.fixture
def operator(conn):
    with db.transaction(conn):
        return operators.create(conn, "Nurse A", "123456", iterations=FAST, at=T0)


def test_pin_hash_is_salted_and_verifiable():
    a = operators.hash_pin("123456", iterations=FAST)
    b = operators.hash_pin("123456", iterations=FAST)
    assert a != b                          # different salt each time
    assert "123456" not in a
    assert operators.verify_hash("123456", a) and not operators.verify_hash("123457", a)


def test_pin_format_is_enforced(conn):
    assert operators.validate_pin_format("123456", 6)
    assert not operators.validate_pin_format("12345", 6)
    assert not operators.validate_pin_format("12345a", 6)
    with pytest.raises(ValueError):
        with db.transaction(conn):
            operators.create(conn, "Nurse B", "12a456", iterations=FAST)


def test_correct_pin_resets_the_failure_counter(conn, operator):
    with db.transaction(conn):
        assert operators.verify(conn, operator, "000000", now=T0)[1] == operators.ERR_WRONG_PIN
    assert operators.get(conn, operator)["failed_attempts"] == 1
    with db.transaction(conn):
        assert operators.verify(conn, operator, "123456", now=T0) == (True, operators.OK)
    assert operators.get(conn, operator)["failed_attempts"] == 0


def test_lockout_after_five_failures(conn, operator):
    for _ in range(4):
        with db.transaction(conn):
            ok, reason = operators.verify(conn, operator, "000000", now=T0)
        assert (ok, reason) == (False, operators.ERR_WRONG_PIN)
    with db.transaction(conn):
        ok, reason = operators.verify(conn, operator, "000000", now=T0)
    assert (ok, reason) == (False, operators.ERR_LOCKED)

    # even the correct PIN is refused while locked
    with db.transaction(conn):
        assert operators.verify(conn, operator, "123456", now=T0 + 100)[1] == operators.ERR_LOCKED
    # ... and works again after the lockout window
    with db.transaction(conn):
        assert operators.verify(conn, operator, "123456", now=T0 + 301) == (True, operators.OK)


def test_unknown_or_inactive_operator(conn, operator):
    with db.transaction(conn):
        assert operators.verify(conn, 999, "123456", now=T0)[1] == operators.ERR_UNKNOWN
        operators.deactivate(conn, operator)
        assert operators.verify(conn, operator, "123456", now=T0)[1] == operators.ERR_INACTIVE
    assert operators.count(conn) == 0


def test_change_pin(conn, operator):
    with db.transaction(conn):
        assert operators.change_pin(conn, operator, "123456", "654321", now=T0,
                                    iterations=FAST) == (True, operators.OK)
    with db.transaction(conn):
        assert operators.verify(conn, operator, "654321", now=T0) == (True, operators.OK)
    with db.transaction(conn):
        ok, reason = operators.change_pin(conn, operator, "654321", "12", now=T0,
                                          iterations=FAST)
    assert (ok, reason) == (False, "bad_format")
