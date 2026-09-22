"""What the kiosk pulls: today's patients, the revocation list, the model bundle.

The gallery is deliberately a day at a time. The clinic works in daily lists (C-04), and
a device that only ever holds today's patients cannot leak last month's.
"""
import base64
import datetime as dt
import hashlib
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from server.auth import require_device, touch_device
from server.db import get_session
from server.models import Appointment, Bundle, FaceTemplate, GalleryVersion, Patient, Revocation
from server.schemas import BundleOut, GalleryOut, PatientOut, RevocationOut, TemplateOut
from server.settings import settings

router = APIRouter(prefix="/api/v1", tags=["gallery"])


def current_version(session, date):
    row = session.get(GalleryVersion, date)
    return row.version if row else 0


@router.get("/gallery", response_model=GalleryOut)
def get_gallery(date: str = Query(default=None), since_version: int = Query(default=0),
                recognizer_sha256: str = Query(default=None),
                device=Depends(require_device), session: Session = Depends(get_session)):
    date = date or dt.date.today().isoformat()
    version = current_version(session, date)
    touch_device(session, device, last_gallery_version=version)
    if version and since_version >= version:
        session.commit()
        # Nothing new: the device keeps what it has and skips the download.
        return GalleryOut(changed=False, date=date, version=version)

    query = (session.query(Patient, Appointment)
             .join(Appointment, Appointment.patient_code == Patient.patient_code)
             .filter(Appointment.procedure_date == date,
                     Patient.revoked_at.is_(None))
             .limit(settings.gallery_page_limit))

    patients = []
    for patient, appointment in query.all():
        templates = session.query(FaceTemplate).filter(
            FaceTemplate.patient_code == patient.patient_code)
        if recognizer_sha256:
            templates = templates.filter(FaceTemplate.recognizer_sha256 == recognizer_sha256)
        rows = templates.all()
        if not rows:
            continue          # a patient without usable templates would only confuse S9
        patients.append(PatientOut(
            patient_code=patient.patient_code, full_name=patient.full_name,
            birth_year=patient.birth_year, appointment_code=appointment.appointment_code,
            templates=[TemplateOut(embedding_b64=base64.b64encode(row.embedding).decode(),
                                   quality=row.quality) for row in rows]))
    session.commit()
    return GalleryOut(changed=True, date=date, version=version,
                      recognizer_sha256=recognizer_sha256, patients=patients)


@router.get("/revocations", response_model=list[RevocationOut])
def get_revocations(since: float = Query(default=0.0), device=Depends(require_device),
                    session: Session = Depends(get_session)):
    cutoff = dt.datetime.fromtimestamp(since, dt.timezone.utc)
    rows = session.query(Revocation).filter(Revocation.revoked_at > cutoff).all()
    return [RevocationOut(patient_code=row.patient_code,
                          revoked_at=row.revoked_at.timestamp(), reason=row.reason)
            for row in rows]


@router.get("/bundles/latest", response_model=BundleOut)
def get_latest_bundle(device=Depends(require_device), session: Session = Depends(get_session)):
    bundle = session.query(Bundle).filter(Bundle.active.is_(True)).one_or_none()
    if bundle is None:
        raise HTTPException(status_code=404, detail="no active bundle")
    return BundleOut(version=bundle.version, sha256=bundle.sha256,
                     signature=bundle.signature, size=bundle.size,
                     url="/api/v1/bundles/{}/file".format(bundle.version))


@router.get("/bundles/{version}/file")
def get_bundle_file(version: str, device=Depends(require_device),
                    session: Session = Depends(get_session)):
    bundle = session.get(Bundle, version)
    if bundle is None or not os.path.exists(bundle.file_path):
        raise HTTPException(status_code=404, detail="bundle not found")
    return FileResponse(bundle.file_path, media_type="application/octet-stream",
                        filename=os.path.basename(bundle.file_path))


def sign_bundle(sha256_hex, version, key):
    """HMAC-SHA256 over the digest and the version (D-24).

    Chosen because the Nano can verify it with the standard library alone: the
    `cryptography` package in Ubuntu 18.04 predates Ed25519 support.
    """
    import hmac

    message = "{}|{}".format(sha256_hex, version).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()
