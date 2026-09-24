# -*- coding: utf-8 -*-
"""Patient face crops (C-24): storage, masking, and the privacy limits on both."""
import os

import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.kiosk.masking import mask_code, mask_name
from edgeface.storage import clock, db, faces, patients

T0 = 1_700_000_000.0


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def a_patient(conn, code="BN0001", at=T0, ttl_hours=24):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, "Nguyễn Thị Hà", 1990, "kiosk", at, ttl_hours)
    return code


def a_crop(value=90):
    return np.full((112, 112, 3), value, dtype=np.uint8)


# ------------------------------------------------------------------ storage


def test_a_face_round_trips(conn):
    code = a_patient(conn)
    jpeg = faces.encode(a_crop())
    assert jpeg and jpeg[:2] == b"\xff\xd8"          # a real JPEG
    with db.transaction(conn):
        assert faces.save(conn, code, jpeg, T0, T0 + 86400.0) is True
    assert faces.get(conn, code) == jpeg
    assert faces.count(conn) == 1


def test_a_crop_stays_small_enough_for_sixty_patients(repo_root):
    """A real face, not synthetic noise: noise does not compress and would measure the
    worst case that never occurs. 60 patients must stay well inside a few hundred KB."""
    import cv2

    image = cv2.imread(os.path.join(repo_root, "tests", "fixtures", "astronaut.jpg"))
    crop = cv2.resize(image[60:180, 180:272], (112, 112))
    jpeg = faces.encode(crop)
    assert len(jpeg) < 5 * 1024                       # measured 3.2 KB
    assert 60 * len(jpeg) < 512 * 1024
    assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape == (112, 112, 3)


def test_a_patient_without_a_face_is_normal_not_an_error(conn):
    """Patients pulled from the server arrive as embeddings only."""
    code = a_patient(conn, "BN-SERVER")
    assert faces.get(conn, code) is None
    assert faces.get_many(conn, [code, "BN-NOBODY"]) == {}


def test_get_many_returns_only_what_exists(conn):
    first, second = a_patient(conn, "BN0001"), a_patient(conn, "BN0002")
    a_patient(conn, "BN0003")
    with db.transaction(conn):
        faces.save(conn, first, faces.encode(a_crop(10)), T0)
        faces.save(conn, second, faces.encode(a_crop(200)), T0)
    found = faces.get_many(conn, [first, second, "BN0003", None])
    assert sorted(found) == ["BN0001", "BN0002"]
    assert found[first] != found[second]


def test_re_enrolling_replaces_the_face_rather_than_failing(conn):
    code = a_patient(conn)
    with db.transaction(conn):
        faces.save(conn, code, faces.encode(a_crop(10)), T0)
        faces.save(conn, code, faces.encode(a_crop(240)), T0 + 60)
    assert faces.count(conn) == 1


# ------------------------------------------------------------------ privacy


def test_the_face_disappears_with_the_expired_patient(conn):
    """C-24 leans on the foreign key rather than on a retention branch, so prove it."""
    code = a_patient(conn, at=T0)
    with db.transaction(conn):
        faces.save(conn, code, faces.encode(a_crop()), T0, T0 + 86400.0)
    assert faces.count(conn) == 1

    with db.transaction(conn):
        patients.delete_expired(conn, T0 + 25 * 3600.0)       # past the 24 h TTL
    assert patients.get(conn, code) is None
    assert faces.get(conn, code) is None and faces.count(conn) == 0


def test_the_face_disappears_when_the_patient_is_revoked(conn):
    code = a_patient(conn)
    with db.transaction(conn):
        faces.save(conn, code, faces.encode(a_crop()), T0)
    with db.transaction(conn):
        patients.revoke(conn, code, "server", T0 + 10)
        patients.delete(conn, code)
    assert faces.count(conn) == 0


# ------------------------------------------------------------------ masking


def test_a_code_keeps_only_its_ends():
    assert mask_code("BN000201") == "BN****01"


def test_a_short_code_never_leaks_more_than_half_of_itself():
    """Keeping two characters of a four-character code would expose half of it."""
    for code in ("BN000201", "BN0001", "BN01", "BN1", "AB", "A"):
        masked = mask_code(code)
        if masked == "***":
            continue
        revealed = sum(1 for ch in masked if ch != "*")
        assert revealed <= len(code) // 2, "{} -> {}".format(code, masked)


def test_an_empty_or_missing_code_is_fully_masked():
    assert mask_code(None) == "***" and mask_code("") == "***" and mask_code("A") == "***"


def test_a_name_is_never_partly_shown():
    """No initials and no length: nothing to recognise a person by."""
    for name in ("Nguyễn Thị Hà", "A", "", None):
        assert mask_name(name) == "***"
