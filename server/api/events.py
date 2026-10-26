"""POST /api/v1/events — the device's outbox arrives here.

Idempotent by event_id: a device that times out mid-upload retries the same batch, and
nothing may be applied twice. One bad event does not spoil the batch; it is reported in
`rejected` and the rest are accepted, otherwise a single malformed payload would block
the queue forever.
"""
import base64
import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.auth import require_device
from server.db import bump_gallery_version, get_session
from server.models import (Appointment, Event, FaceTemplate, Patient, Revocation,
                           SessionLog, SpoofEvent)
from server.schemas import EventBatch, EventResult
from server.settings import settings

router = APIRouter(prefix="/api/v1", tags=["events"])

EMBEDDING_BYTES = 512 * 4


def _to_datetime(epoch):
    if epoch is None:
        return None
    return dt.datetime.fromtimestamp(float(epoch), dt.timezone.utc)


def _apply_enrollment(session, device_id, payload):
    code = payload["patient_code"]
    patient = session.get(Patient, code)
    if patient is None:
        patient = Patient(patient_code=code, full_name=payload.get("full_name") or code,
                          birth_year=payload.get("birth_year"))
        session.add(patient)
    else:
        patient.full_name = payload.get("full_name") or patient.full_name
        patient.birth_year = payload.get("birth_year", patient.birth_year)
        patient.revoked_at = None       # re-enrolling clears a previous revocation

    procedure_date = payload.get("procedure_date") or dt.date.today().isoformat()
    appointment_code = payload.get("appointment_code")
    if appointment_code:
        appointment = session.get(Appointment, appointment_code)
        if appointment is None:
            session.add(Appointment(appointment_code=appointment_code, patient_code=code,
                                    procedure_date=procedure_date))
        else:
            appointment.patient_code = code
            appointment.procedure_date = procedure_date

    templates = payload.get("templates") or []
    if not templates:
        raise ValueError("enrollment without templates")
    # The device is the source of truth for its own enrollment: replace, do not append,
    # so re-sending a corrected batch cannot double a patient's templates.
    session.query(FaceTemplate).filter(
        FaceTemplate.patient_code == code,
        FaceTemplate.source_device_id == device_id).delete(synchronize_session=False)
    for item in templates:
        blob = base64.b64decode(item["embedding_b64"])
        if len(blob) != EMBEDDING_BYTES:
            raise ValueError("embedding is {} bytes, expected {}".format(
                len(blob), EMBEDDING_BYTES))
        session.add(FaceTemplate(patient_code=code, embedding=blob,
                                 quality=item.get("quality"),
                                 recognizer_sha256=payload["recognizer_sha256"],
                                 source_device_id=device_id))
    bump_gallery_version(session, procedure_date)


def _apply_session_closed(session, device_id, payload):
    session_id = payload.get("session_id")
    if not session_id:
        raise ValueError("session.closed without a session_id")
    row = session.get(SessionLog, session_id)
    if row is None:
        row = SessionLog(session_id=session_id)
        session.add(row)
    row.device_id = device_id
    row.kind = payload.get("kind")
    row.started_at = _to_datetime(payload.get("started_at"))
    row.decision = payload.get("decision")
    row.rule_id = payload.get("rule_id")
    row.top1_code = payload.get("top1_code")
    row.top1_score = payload.get("top1_score")
    row.votes = payload.get("votes")
    row.n_good_frames = payload.get("n_good_frames")
    row.spoof_frames = payload.get("spoof_frames")
    row.nurse_action = payload.get("nurse_action")
    row.confirmed_code = payload.get("confirmed_code")
    row.operator_id = payload.get("operator_id")


def _apply_spoof(session, device_id, event_id, payload):
    session.merge(SpoofEvent(event_id=event_id, device_id=device_id,
                             session_id=payload.get("session_id"),
                             min_p_real=payload.get("min_p_real"),
                             spoof_frames=payload.get("spoof_frames"),
                             evidence_sha256=payload.get("evidence_sha256")))


def _apply_revoked_local(session, device_id, payload):
    code = payload.get("patient_code")
    if not code:
        raise ValueError("revocation without a patient_code")
    patient = session.get(Patient, code)
    if patient is not None:
        patient.revoked_at = dt.datetime.now(dt.timezone.utc)
        patient.revoke_reason = payload.get("reason")
    session.merge(Revocation(patient_code=code, reason=payload.get("reason")))


HANDLERS = {
    "enrollment.created": lambda s, d, e, p: _apply_enrollment(s, d, p),
    "session.closed": lambda s, d, e, p: _apply_session_closed(s, d, p),
    "spoof.detected": lambda s, d, e, p: _apply_spoof(s, d, e, p),
    "patient.revoked_local": lambda s, d, e, p: _apply_revoked_local(s, d, p),
    "device.heartbeat": lambda s, d, e, p: None,
    # A nurse changed a match threshold on the kiosk. Nothing to apply here: storing the
    # event row is the point, as the audit trail of who changed what and when.
    "settings.changed": lambda s, d, e, p: None,
}


@router.post("/events", response_model=EventResult)
def post_events(batch: EventBatch, device=Depends(require_device),
                session: Session = Depends(get_session)):
    if len(batch.events) > settings.max_events_per_request:
        raise HTTPException(status_code=413, detail="too many events in one request")

    result = EventResult()
    for event in batch.events:
        if session.get(Event, event.event_id) is not None:
            result.duplicate.append(event.event_id)
            continue
        handler = HANDLERS.get(event.type)
        if handler is None:
            result.rejected.append({"event_id": event.event_id,
                                    "error": "unknown type " + event.type})
            continue
        try:
            with session.begin_nested():
                handler(session, device.device_id, event.event_id, event.payload)
                session.add(Event(event_id=event.event_id, device_id=device.device_id,
                                  type=event.type, payload=json.dumps(event.payload),
                                  received_at=_to_datetime(event.created_at)))
            result.accepted.append(event.event_id)
        except Exception as exc:        # noqa: BLE001 - one bad event must not block the rest
            result.rejected.append({"event_id": event.event_id, "error": str(exc)[:200]})

    device.last_seen_at = dt.datetime.now(dt.timezone.utc)
    session.commit()
    return result
