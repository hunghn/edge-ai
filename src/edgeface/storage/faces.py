# -*- coding: utf-8 -*-
"""One enrolment face crop per patient (C-24).

Why these exist at all: an embedding cannot be turned back into a picture, and when the
system says "this face is already enrolled under another code", the nurse has to decide
whether that is the same person registering twice or two people who look alike. Only a
face answers that question. The other patient's name is not needed for it, and is masked
on screen (kiosk/masking.py) — the picture identifies without naming.

This reverses C-04 for this one case, so the limits are deliberately tight:

- stored as a BLOB, in the database, not as loose files: no path to leak, and the row
  cascades away with the patient at the 24 h expiry or on a revocation;
- never entered into the outbox, so a face never reaches the server;
- only read by the duplicate-warning screen.
"""
from edgeface.storage import clock
from edgeface.storage.db import read_all, read_one

JPEG_QUALITY = 80             # ~3 KB for a 112x112 crop


def encode(image):
    """112x112 BGR crop -> JPEG bytes, or None when it cannot be encoded."""
    import cv2

    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return buffer.tobytes() if ok else None


def save(conn, patient_code, jpeg_bytes, at=None, expires_at=None):
    """Store (or replace) one patient's face. Call inside db.transaction().

    `expires_at` should be the patient's own expiry so the two agree, though the cascade
    is what actually removes the row.
    """
    if not jpeg_bytes:
        return False
    at = clock.now() if at is None else at
    conn.execute("INSERT OR REPLACE INTO patient_faces "
                 "(patient_code, jpeg, created_at, expires_at) VALUES (?, ?, ?, ?)",
                 (patient_code, memoryview(jpeg_bytes), at, expires_at))
    return True


def get(conn, patient_code):
    """JPEG bytes, or None when this patient has no picture.

    None is normal, not an error: patients pulled from the server arrive as embeddings
    only, so the screen shows an empty frame for them.
    """
    row = read_one(conn, "SELECT jpeg FROM patient_faces WHERE patient_code = ?",
                   (patient_code,))
    return None if row is None else bytes(row["jpeg"])


def get_many(conn, codes):
    """{code: jpeg_bytes} for the codes that have one; missing codes are simply absent."""
    codes = [c for c in (codes or []) if c]
    if not codes:
        return {}
    marks = ",".join("?" * len(codes))
    rows = read_all(conn, "SELECT patient_code, jpeg FROM patient_faces "
                          "WHERE patient_code IN ({})".format(marks), tuple(codes))
    return {row["patient_code"]: bytes(row["jpeg"]) for row in rows}


def delete(conn, patient_code):
    return conn.execute("DELETE FROM patient_faces WHERE patient_code = ?",
                        (patient_code,)).rowcount


def count(conn):
    return read_one(conn, "SELECT COUNT(*) AS n FROM patient_faces")["n"]
