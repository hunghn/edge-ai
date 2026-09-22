"""Pull today's gallery and the revocation list into the local database.

Two rules the clinic depends on:
  - a revocation always wins, and takes the patient's templates with it, whether they
    came from the server or were enrolled at the kiosk;
  - patients enrolled locally are never deleted by a gallery pull, because the server may
    not have heard about them yet (the outbox may still be queued).
"""
from edgeface.common.log import get_logger
from edgeface.storage import clock, patients, templates
from edgeface.storage.db import get_meta, set_meta, transaction

LOG = get_logger("sync.pull")

LAST_PULL_KEY = "last_pull_at"
LAST_REVOCATION_KEY = "last_revocation_at"
SERVER_VERSION_KEY = "server_gallery_version"


def decode_templates(items):
    import base64

    return [(base64.b64decode(item["embedding_b64"]), item.get("quality"))
            for item in items or []]


def apply_gallery(conn, payload, recognizer_sha256, now=None, ttl_hours=24):
    """Replace the server-sourced part of the gallery. Returns a summary dict."""
    now = clock.now() if now is None else now
    if not payload or payload.get("changed") is False:
        return {"changed": False, "patients": 0, "removed": 0}

    incoming = payload.get("patients") or []
    keep = set(row["patient_code"] for row in incoming)
    summary = {"changed": True, "patients": 0, "templates": 0, "removed": 0}

    with transaction(conn):
        existing = conn.execute(
            "SELECT patient_code FROM patients WHERE source = 'server'").fetchall()
        for row in existing:
            code = row["patient_code"]
            if code not in keep:
                patients.delete(conn, code)      # no longer on today's list
                summary["removed"] += 1

        for row in incoming:
            code = row["patient_code"]
            patients.upsert_patient(conn, code, row.get("full_name") or code,
                                    row.get("birth_year"), patients.SOURCE_SERVER, now,
                                    ttl_hours)
            if row.get("appointment_code"):
                patients.upsert_appointment(conn, row["appointment_code"], code,
                                            payload.get("date")
                                            or clock.local_date(now))
            decoded = decode_templates(row.get("templates"))
            if decoded:
                templates.delete_for_patient(conn, code)
                for blob, quality in decoded:
                    conn.execute(
                        "INSERT INTO face_templates (patient_code, embedding, quality, "
                        "recognizer_sha256, created_at) VALUES (?, ?, ?, ?, ?)",
                        (code, blob, quality, recognizer_sha256, now))
                summary["templates"] += len(decoded)
            summary["patients"] += 1

        templates.bump_gallery_version(conn)
        set_meta(conn, LAST_PULL_KEY, now)
        if payload.get("version") is not None:
            set_meta(conn, SERVER_VERSION_KEY, payload["version"])
    LOG.info("gallery pulled: %s", summary)
    return summary


def apply_revocations(conn, rows, now=None):
    """Delete every revoked patient locally, whatever their source."""
    now = clock.now() if now is None else now
    if not rows:
        return {"revoked": 0}
    latest = float(get_meta(conn, LAST_REVOCATION_KEY, 0) or 0)
    with transaction(conn):
        for row in rows:
            code = row["patient_code"]
            patients.revoke(conn, code, row.get("reason"), row.get("revoked_at", now))
            patients.delete(conn, code)
            latest = max(latest, float(row.get("revoked_at") or now))
        templates.bump_gallery_version(conn)
        set_meta(conn, LAST_REVOCATION_KEY, latest)
    LOG.warning("applied %d revocation(s)", len(rows))
    return {"revoked": len(rows)}


def pull_once(conn, client, recognizer_sha256, now=None, ttl_hours=24, date=None):
    """One full pull: revocations first, then the gallery."""
    now = clock.now() if now is None else now
    since = float(get_meta(conn, LAST_REVOCATION_KEY, 0) or 0)
    result = {}
    result.update(apply_revocations(conn, client.get_revocations(since), now))
    server_version = int(get_meta(conn, SERVER_VERSION_KEY, 0) or 0)
    payload = client.get_gallery(date=date, since_version=server_version,
                                 recognizer_sha256=recognizer_sha256)
    result.update(apply_gallery(conn, payload, recognizer_sha256, now, ttl_hours))
    return result
