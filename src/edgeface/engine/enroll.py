"""Enrollment: turn a burst of good frames into a patient's templates.

C-22: the five samples are captured automatically once the frames pass the same gates as
identification, anti-spoofing included — nobody is enrolled from a photo. If the face
matches a patient who is already in the gallery, the nurse is warned and can still
confirm (twins, or the same person entered twice under different codes).
"""
import base64
from collections import namedtuple

import numpy as np

from edgeface.common.log import get_logger
from edgeface.pipeline import matcher
from edgeface.storage import clock, faces, patients, templates
from edgeface.storage.db import transaction
from edgeface.storage.outbox import enqueue

LOG = get_logger("enroll")

REQUIRED_FIELDS = ("patient_code", "full_name")

EnrollReview = namedtuple("EnrollReview", [
    "form", "n_templates", "duplicate_code", "duplicate_score", "self_consistency",
    "blocked", "warnings", "duplicates",
])
# duplicates: [(patient_code, score), ...], closest first. Two or more people can look
# alike, so the nurse is shown a list, not just the single nearest patient.
EnrollReview.__new__.__defaults__ = ((),)


def validate_form(form, conn=None):
    """(ok, reason). Checked before the camera starts, so nothing is captured in vain."""
    if not form:
        return False, "missing_form"
    for field in REQUIRED_FIELDS:
        if not form.get(field):
            return False, "missing_" + field
    birth_year = form.get("birth_year")
    if birth_year is not None:
        try:
            year = int(birth_year)
        except (TypeError, ValueError):
            return False, "bad_birth_year"
        if not 1900 <= year <= 2100:
            return False, "bad_birth_year"
    return True, None


def self_consistency(vectors):
    """Mean pairwise cosine of the captured templates.

    A low value means the burst caught two different faces (someone walked past), which
    would poison the gallery entry.
    """
    if len(vectors) < 2:
        return None
    stack = np.asarray(vectors, dtype=np.float32)
    similarity = stack.dot(stack.T)
    upper = similarity[np.triu_indices(len(vectors), k=1)]
    return float(np.mean(upper))


def review(form, embeddings, gallery, cfg):
    """Everything the nurse needs to decide, before anything is written."""
    enroll_cfg = cfg["enroll"]
    vectors = [np.asarray(e.vector, dtype=np.float32) for e in embeddings]
    warnings = []

    consistency = self_consistency(vectors)
    min_consistency = enroll_cfg.get("self_consistency_min")
    if consistency is not None and min_consistency is not None and consistency < min_consistency:
        warnings.append("inconsistent_capture")

    duplicates = matcher.top_matches_for(
        vectors, gallery, cfg, limit=enroll_cfg.get("duplicate_list_max", 3),
        min_score=enroll_cfg.get("duplicate_show_min"),
        exclude_code=form.get("patient_code"))
    duplicate_code, duplicate_score = duplicates[0] if duplicates else (None, None)

    threshold = enroll_cfg.get("duplicate_threshold")
    if threshold is None:
        threshold = cfg["match"].get("threshold")
    is_duplicate = (duplicate_code is not None and threshold is not None
                    and duplicate_score >= threshold)
    if is_duplicate:
        warnings.append("duplicate_face")
    elif threshold is None and duplicate_code is not None:
        # No calibrated threshold yet (D-01): show the closest patients and let the nurse
        # judge. The screen says the threshold is uncalibrated rather than implying that
        # everyone on the list is a genuine duplicate.
        warnings.append("duplicate_unknown_threshold")

    blocked = is_duplicate and enroll_cfg.get("duplicate_policy") == "block"
    return EnrollReview(form=form, n_templates=len(vectors), duplicate_code=duplicate_code,
                        duplicate_score=duplicate_score, self_consistency=consistency,
                        blocked=blocked, warnings=warnings, duplicates=tuple(duplicates))


def commit(conn, form, embeddings, cfg, recognizer_sha256, operator_id=None, now=None,
           session_id=None, face_jpeg=None):
    """Write the patient, the appointment and the templates in one transaction.

    The outbox event goes in the same transaction: either the server hears about this
    enrollment or the enrollment did not happen.

    `face_jpeg` is the enrolment crop kept for the duplicate warning (C-24). It is
    written to the database and deliberately left out of the outbox event: the face
    stays on this machine.
    """
    now = clock.now() if now is None else now
    ttl_hours = cfg["retention"]["patients_hours"]
    vectors = [np.asarray(e.vector, dtype=np.float32) for e in embeddings]
    qualities = [e.quality for e in embeddings]

    with transaction(conn):
        patients.upsert_patient(conn, form["patient_code"], form["full_name"],
                                form.get("birth_year"), patients.SOURCE_KIOSK, now,
                                ttl_hours)
        if form.get("appointment_code"):
            patients.upsert_appointment(conn, form["appointment_code"], form["patient_code"],
                                        form.get("procedure_date") or clock.local_date(now))
        templates.add_templates(conn, form["patient_code"], vectors, recognizer_sha256,
                                qualities, now)
        if face_jpeg:
            faces.save(conn, form["patient_code"], face_jpeg, now,
                       now + ttl_hours * 3600.0)
        # Note what this payload does NOT contain: the face. Templates are vectors and
        # cannot be turned back into a picture, and that property is the reason the
        # server never receives one.
        event_id = enqueue(conn, "enrollment.created", {
            "patient_code": form["patient_code"],
            "full_name": form["full_name"],
            "birth_year": form.get("birth_year"),
            "appointment_code": form.get("appointment_code"),
            "recognizer_sha256": recognizer_sha256,
            "operator_id": operator_id,
            "session_id": session_id,
            "templates": [
                {"embedding_b64": base64.b64encode(templates.encode(v)).decode("ascii"),
                 "quality": q} for v, q in zip(vectors, qualities)],
        }, at=now)
    LOG.info("enrolled %s with %d templates (event %s)", form["patient_code"],
             len(vectors), event_id)
    return {"patient_code": form["patient_code"], "n_templates": len(vectors),
            "event_id": event_id, "gallery_version": templates.gallery_version(conn)}
