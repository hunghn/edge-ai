import numpy as np
import pytest

from edgeface.storage import db, patients, templates

T0 = 1_700_000_000.0
SHA_A = "sha-model-a"
SHA_B = "sha-model-b"


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def unit(seed, dim=512):
    rng = np.random.RandomState(seed)
    v = rng.randn(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def enroll(conn, code, vectors, sha=SHA_A, at=T0, ttl_hours=24):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, code, 1990, "kiosk", at, ttl_hours)
        templates.add_templates(conn, code, vectors, sha, created_at=at)


def test_embedding_roundtrip_is_exact():
    v = unit(0)
    np.testing.assert_array_equal(templates.decode(templates.encode(v)), v)


def test_encode_rejects_wrong_shape():
    with pytest.raises(ValueError):
        templates.encode(np.zeros(128, dtype=np.float32))


def test_gallery_matrix_groups_rows_by_patient(conn):
    enroll(conn, "BN001", [unit(1), unit(2)])
    enroll(conn, "BN002", [unit(3)])
    codes, matrix, owner = templates.load_gallery(conn, SHA_A, now=T0)
    assert codes == ["BN001", "BN002"]
    assert matrix.shape == (3, 512) and matrix.dtype == np.float32
    assert list(owner) == [0, 0, 1]
    np.testing.assert_allclose(matrix[2], unit(3))


def test_gallery_filters_by_recognizer_sha(conn):
    enroll(conn, "BN001", [unit(1)], sha=SHA_A)
    enroll(conn, "BN002", [unit(2)], sha=SHA_B)
    codes, matrix, _ = templates.load_gallery(conn, SHA_A, now=T0)
    assert codes == ["BN001"] and matrix.shape == (1, 512)


def test_gallery_excludes_expired_and_revoked(conn):
    enroll(conn, "BN001", [unit(1)], at=T0)
    enroll(conn, "BN002", [unit(2)], at=T0)
    with db.transaction(conn):
        patients.revoke(conn, "BN002", "test", T0 + 10)
    codes, _, _ = templates.load_gallery(conn, SHA_A, now=T0 + 20)
    assert codes == ["BN001"]
    codes, matrix, owner = templates.load_gallery(conn, SHA_A, now=T0 + 25 * 3600)
    assert codes == [] and matrix.shape == (0, 512) and owner.shape == (0,)


def test_version_bumps_on_enrollment(conn):
    assert templates.gallery_version(conn) == 0
    enroll(conn, "BN001", [unit(1)])
    assert templates.gallery_version(conn) == 1
    enroll(conn, "BN002", [unit(2)])
    assert templates.gallery_version(conn) == 2


def test_qualities_must_match_embeddings(conn):
    with pytest.raises(ValueError):
        with db.transaction(conn):
            patients.upsert_patient(conn, "BN001", "A", 1990, "kiosk", T0)
            templates.add_templates(conn, "BN001", [unit(1), unit(2)], SHA_A, qualities=[0.9])


def test_deleting_the_patient_removes_templates(conn):
    enroll(conn, "BN001", [unit(1), unit(2)])
    with db.transaction(conn):
        patients.delete(conn, "BN001")
    assert templates.count(conn) == 0
