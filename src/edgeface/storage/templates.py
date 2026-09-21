"""Face templates (embeddings) and the gallery matrix used by S9.

An embedding is stored as 512 little-endian float32 values. Every row records the
sha256 of the recognizer that produced it: embeddings from different models are not
comparable, so the gallery loader filters on it.
"""
import numpy as np

from edgeface.storage import clock
from edgeface.storage.db import read_all, set_meta

EMBEDDING_DIM = 512
_DTYPE = np.dtype("<f4")


def encode(vector):
    vec = np.asarray(vector, dtype=_DTYPE)
    if vec.shape != (EMBEDDING_DIM,):
        raise ValueError("expected a ({},) embedding, got {}".format(EMBEDDING_DIM, vec.shape))
    return vec.tobytes()


def decode(blob):
    vec = np.frombuffer(blob, dtype=_DTYPE)
    if vec.shape != (EMBEDDING_DIM,):
        raise ValueError("corrupt embedding blob of length {}".format(len(blob)))
    return vec.astype(np.float32)


def add_templates(conn, patient_code, embeddings, recognizer_sha256, qualities=None,
                  created_at=None):
    """Add N templates for one patient and bump the gallery version.

    Must be called inside db.transaction(): the engine reloads the gallery on a version
    change, so the rows and the version have to become visible together.
    """
    created_at = clock.now() if created_at is None else created_at
    embeddings = list(embeddings)
    if qualities is None:
        qualities = [None] * len(embeddings)
    if len(qualities) != len(embeddings):
        raise ValueError("qualities and embeddings have different lengths")
    for vector, quality in zip(embeddings, qualities):
        conn.execute(
            "INSERT INTO face_templates (patient_code, embedding, quality, recognizer_sha256, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (patient_code, encode(vector), quality, recognizer_sha256, created_at))
    bump_gallery_version(conn)
    return len(embeddings)


def delete_for_patient(conn, patient_code):
    return conn.execute("DELETE FROM face_templates WHERE patient_code = ?",
                        (patient_code,)).rowcount


def count(conn, patient_code=None):
    if patient_code is None:
        row = conn.execute("SELECT COUNT(*) AS n FROM face_templates").fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS n FROM face_templates WHERE patient_code = ?",
                           (patient_code,)).fetchone()
    return int(row["n"])


def gallery_version(conn):
    row = conn.execute("SELECT value FROM gallery_meta WHERE key = 'version'").fetchone()
    return int(row["value"]) if row is not None else 0


def bump_gallery_version(conn):
    new_version = gallery_version(conn) + 1
    set_meta(conn, "version", new_version)
    return new_version


def load_gallery_rows(conn, recognizer_sha256, now=None):
    """Templates eligible for matching: patient not expired, not revoked, same recognizer."""
    now = clock.now() if now is None else now
    return read_all(
        conn,
        "SELECT t.template_id, t.patient_code, t.embedding, t.quality FROM face_templates t "
        "JOIN patients p ON p.patient_code = t.patient_code "
        "WHERE t.recognizer_sha256 = ? AND p.expires_at > ? AND p.revoked_at IS NULL "
        "ORDER BY t.patient_code, t.template_id",
        (recognizer_sha256, now))


def load_gallery(conn, recognizer_sha256, now=None):
    """(codes, matrix, owner) ready for S9.

    codes  : list of N patient codes, in matrix order
    matrix : (M, 512) float32, M templates
    owner  : (M,) int32, index into codes for each row
    Rows are grouped by patient (the SQL orders by patient_code), which lets the matcher
    aggregate per patient with np.maximum.reduceat.
    """
    rows = load_gallery_rows(conn, recognizer_sha256, now)
    if not rows:
        return [], np.zeros((0, EMBEDDING_DIM), dtype=np.float32), np.zeros((0,), dtype=np.int32)
    codes, owner, vectors = [], [], []
    for row in rows:
        code = row["patient_code"]
        if not codes or codes[-1] != code:
            codes.append(code)
        owner.append(len(codes) - 1)
        vectors.append(decode(row["embedding"]))
    return codes, np.vstack(vectors).astype(np.float32), np.asarray(owner, dtype=np.int32)
