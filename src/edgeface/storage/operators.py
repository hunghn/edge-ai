"""Nurse accounts and the PIN that unlocks the kiosk admin screen.

C-18: 6-digit PIN, locked for 5 minutes after 5 wrong attempts. PINs are stored as
PBKDF2-HMAC-SHA256 with a per-operator salt, never in clear text.
"""
import binascii
import hashlib
import hmac
import os

from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

DEFAULT_ITERATIONS = 100000
_ALGO = "pbkdf2_sha256"

OK = "ok"
ERR_UNKNOWN = "unknown_operator"
ERR_LOCKED = "locked"
ERR_WRONG_PIN = "wrong_pin"
ERR_INACTIVE = "inactive"


def hash_pin(pin, iterations=DEFAULT_ITERATIONS, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, iterations)
    return "{}${}${}${}".format(_ALGO, iterations, binascii.hexlify(salt).decode(),
                                binascii.hexlify(digest).decode())


def verify_hash(pin, stored):
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"),
                                 binascii.unhexlify(salt_hex), int(iterations))
    return hmac.compare_digest(binascii.hexlify(digest).decode(), hash_hex)


def validate_pin_format(pin, length=6):
    return isinstance(pin, str) and len(pin) == length and pin.isdigit()


def create(conn, display_name, pin, iterations=DEFAULT_ITERATIONS, pin_length=6, at=None):
    if not validate_pin_format(pin, pin_length):
        raise ValueError("PIN must be exactly {} digits".format(pin_length))
    at = clock.now() if at is None else at
    cur = conn.execute(
        "INSERT INTO operators (display_name, pin_hash, created_at) VALUES (?, ?, ?)",
        (display_name, hash_pin(pin, iterations), at))
    return int(cur.lastrowid)


def get(conn, operator_id):
    return read_one(conn, "SELECT * FROM operators WHERE operator_id = ?", (operator_id,))


def list_active(conn):
    return read_all(conn, "SELECT operator_id, display_name, locked_until, failed_attempts "
                          "FROM operators WHERE active = 1 ORDER BY display_name")


def verify(conn, operator_id, pin, now=None, max_failed=5, lockout_s=300):
    """(ok, reason). Counts failures and locks the account; resets the counter on success.

    Must run inside db.transaction(): the attempt counter has to move with the check.
    """
    now = clock.now() if now is None else now
    row = get(conn, operator_id)
    if row is None:
        return False, ERR_UNKNOWN
    if not row["active"]:
        return False, ERR_INACTIVE
    if row["locked_until"] is not None and now < row["locked_until"]:
        return False, ERR_LOCKED

    if verify_hash(pin, row["pin_hash"]):
        conn.execute("UPDATE operators SET failed_attempts = 0, locked_until = NULL "
                     "WHERE operator_id = ?", (operator_id,))
        return True, OK

    attempts = int(row["failed_attempts"]) + 1
    if attempts >= max_failed:
        conn.execute("UPDATE operators SET failed_attempts = 0, locked_until = ? "
                     "WHERE operator_id = ?", (now + lockout_s, operator_id))
        return False, ERR_LOCKED
    conn.execute("UPDATE operators SET failed_attempts = ? WHERE operator_id = ?",
                 (attempts, operator_id))
    return False, ERR_WRONG_PIN


def change_pin(conn, operator_id, old_pin, new_pin, now=None, iterations=DEFAULT_ITERATIONS,
               pin_length=6, max_failed=5, lockout_s=300):
    ok, reason = verify(conn, operator_id, old_pin, now, max_failed, lockout_s)
    if not ok:
        return False, reason
    if not validate_pin_format(new_pin, pin_length):
        return False, "bad_format"
    conn.execute("UPDATE operators SET pin_hash = ? WHERE operator_id = ?",
                 (hash_pin(new_pin, iterations), operator_id))
    return True, OK


def deactivate(conn, operator_id):
    return conn.execute("UPDATE operators SET active = 0 WHERE operator_id = ?",
                        (operator_id,)).rowcount


def count(conn):
    return int(conn.execute("SELECT COUNT(*) AS n FROM operators WHERE active = 1"
                            ).fetchone()["n"])
