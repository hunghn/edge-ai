"""Patients and appointments.

Records are minimal by design (C-04): code, name, birth year, appointment code and the
face templates. No face image is ever stored here.
"""
import unicodedata

from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

SOURCE_KIOSK = "kiosk"
SOURCE_SERVER = "server"


def strip_accents(text):
    """'Nguyễn Thị Hà' -> 'nguyen thi ha' so a nurse can search without diacritics."""
    if text is None:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.replace("đ", "d").replace("Đ", "D").lower().strip()


def upsert_patient(conn, patient_code, full_name, birth_year=None, source=SOURCE_KIOSK,
                   created_at=None, ttl_hours=24):
    """Insert or update one patient. Must be called inside db.transaction().

    UPDATE-then-INSERT instead of INSERT OR REPLACE: REPLACE deletes the old row, which
    would cascade and silently drop the patient's face templates and appointments.
    """
    created_at = clock.now() if created_at is None else created_at
    expires_at = created_at + ttl_hours * 3600.0
    name_search = strip_accents(full_name)
    cur = conn.execute(
        "UPDATE patients SET full_name = ?, name_search = ?, birth_year = ?, source = ?, "
        "expires_at = ?, revoked_at = NULL WHERE patient_code = ?",
        (full_name, name_search, birth_year, source, expires_at, patient_code))
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO patients (patient_code, full_name, name_search, birth_year, source, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (patient_code, full_name, name_search, birth_year, source, created_at, expires_at))
        return "inserted"
    return "updated"


def upsert_appointment(conn, appointment_code, patient_code, procedure_date, status="scheduled"):
    cur = conn.execute(
        "UPDATE appointments SET patient_code = ?, procedure_date = ?, status = ? "
        "WHERE appointment_code = ?",
        (patient_code, procedure_date, status, appointment_code))
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO appointments (appointment_code, patient_code, procedure_date, status) "
            "VALUES (?, ?, ?, ?)", (appointment_code, patient_code, procedure_date, status))
        return "inserted"
    return "updated"


def get(conn, patient_code):
    return read_one(conn, "SELECT * FROM patients WHERE patient_code = ?", (patient_code,))


def get_with_appointment(conn, patient_code, procedure_date=None):
    """Patient plus today's appointment code, for the candidate card on the kiosk."""
    patient = get(conn, patient_code)
    if patient is None:
        return None
    date = procedure_date or clock.local_date(clock.now())
    appt = read_one(conn, "SELECT appointment_code, status FROM appointments "
                          "WHERE patient_code = ? AND procedure_date = ?", (patient_code, date))
    patient["appointment_code"] = appt["appointment_code"] if appt else None
    patient["appointment_status"] = appt["status"] if appt else None
    return patient


def search(conn, query, limit=20, now=None):
    """Manual lookup by code or name. Accent-insensitive; excludes expired/revoked."""
    now = clock.now() if now is None else now
    pattern = "%" + strip_accents(query) + "%"
    code_pattern = "%" + (query or "").upper().strip() + "%"
    return read_all(
        conn,
        "SELECT * FROM patients WHERE expires_at > ? AND revoked_at IS NULL "
        "AND (name_search LIKE ? OR UPPER(patient_code) LIKE ?) "
        "ORDER BY full_name LIMIT ?",
        (now, pattern, code_pattern, limit))


def list_active(conn, now=None, limit=200):
    now = clock.now() if now is None else now
    return read_all(
        conn, "SELECT * FROM patients WHERE expires_at > ? AND revoked_at IS NULL "
              "ORDER BY created_at DESC LIMIT ?", (now, limit))


def list_for_date(conn, procedure_date, now=None, limit=200):
    now = clock.now() if now is None else now
    return read_all(
        conn,
        "SELECT p.*, a.appointment_code, a.status AS appointment_status FROM patients p "
        "JOIN appointments a ON a.patient_code = p.patient_code "
        "WHERE a.procedure_date = ? AND p.expires_at > ? AND p.revoked_at IS NULL "
        "ORDER BY p.full_name LIMIT ?", (procedure_date, now, limit))


def revoke(conn, patient_code, reason=None, at=None):
    """Mark revoked and record it. retention.run_once() does the actual deletion."""
    at = clock.now() if at is None else at
    conn.execute("UPDATE patients SET revoked_at = ? WHERE patient_code = ?", (at, patient_code))
    cur = conn.execute("UPDATE revocations SET revoked_at = ?, reason = ? WHERE patient_code = ?",
                       (at, reason, patient_code))
    if cur.rowcount == 0:
        conn.execute("INSERT INTO revocations (patient_code, revoked_at, reason) VALUES (?, ?, ?)",
                     (patient_code, at, reason))


def delete(conn, patient_code):
    """Delete a patient; templates and appointments go with it (ON DELETE CASCADE)."""
    return conn.execute("DELETE FROM patients WHERE patient_code = ?", (patient_code,)).rowcount


def delete_expired(conn, now=None):
    now = clock.now() if now is None else now
    return conn.execute("DELETE FROM patients WHERE expires_at <= ?", (now,)).rowcount


def apply_revocations(conn, now=None):
    """Delete every patient that appears in the revocation list. Returns the count."""
    return conn.execute(
        "DELETE FROM patients WHERE patient_code IN (SELECT patient_code FROM revocations)"
    ).rowcount


def count_active(conn, now=None):
    now = clock.now() if now is None else now
    row = conn.execute("SELECT COUNT(*) AS n FROM patients WHERE expires_at > ? "
                       "AND revoked_at IS NULL", (now,)).fetchone()
    return int(row["n"])
