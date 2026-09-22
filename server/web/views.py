# -*- coding: utf-8 -*-
"""Admin web UI: server-rendered pages, no JavaScript framework.

Everything a clinic needs to run the day: who is enrolled, what happened at the kiosk,
which faces were rejected as spoofs, and the switch to revoke someone.
"""
import csv
import datetime as dt
import io
import os

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from server.auth import current_admin, hash_password, require_admin, verify_password
from server.web.csrf import require_csrf, token_for
from server.db import bump_gallery_version, get_session
from server.models import (Admin, Appointment, Device, FaceTemplate, Patient, Revocation,
                           SessionLog, SpoofEvent)

router = APIRouter(prefix="/admin", tags=["web"])
TEMPLATES = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                   "templates"))
CSV_COLUMNS = ("patient_code", "full_name", "birth_year", "appointment_code",
               "procedure_date")


def render(request, name, **context):
    context.setdefault("today", dt.date.today().isoformat())
    context.setdefault("csrf_token", token_for(request))
    return TEMPLATES.TemplateResponse(request, name, context)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str = None):
    return render(request, "login.html", error=error)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...),
          _csrf=Depends(require_csrf), session: Session = Depends(get_session)):
    admin = session.get(Admin, username)
    if admin is None or not verify_password(password, admin.password_hash):
        return RedirectResponse("/admin/login?error=1", status_code=303)
    request.session["admin"] = username
    return RedirectResponse("/admin/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def overview(request: Request, admin=Depends(require_admin),
             session: Session = Depends(get_session)):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    by_decision = dict(session.query(SessionLog.decision, func.count())
                       .filter(SessionLog.started_at >= since)
                       .group_by(SessionLog.decision).all())
    by_action = dict(session.query(SessionLog.nurse_action, func.count())
                     .filter(SessionLog.started_at >= since)
                     .group_by(SessionLog.nurse_action).all())
    return render(request, "overview.html",
                  by_decision=by_decision, by_action=by_action,
                  spoof_count=session.query(SpoofEvent)
                  .filter(SpoofEvent.received_at >= since).count(),
                  devices=session.query(Device).all(),
                  patient_count=session.query(Patient)
                  .filter(Patient.revoked_at.is_(None)).count())


@router.get("/patients", response_class=HTMLResponse)
def patients_page(request: Request, q: str = "", admin=Depends(require_admin),
                  session: Session = Depends(get_session)):
    query = session.query(Patient)
    if q:
        like = "%{}%".format(q)
        query = query.filter(Patient.full_name.ilike(like) | Patient.patient_code.ilike(like))
    rows = []
    for patient in query.order_by(Patient.patient_code).limit(200).all():
        rows.append({
            "patient": patient,
            "templates": session.query(FaceTemplate)
            .filter(FaceTemplate.patient_code == patient.patient_code).count(),
            "appointments": session.query(Appointment)
            .filter(Appointment.patient_code == patient.patient_code)
            .order_by(Appointment.procedure_date.desc()).limit(3).all(),
        })
    return render(request, "patients.html", rows=rows, q=q)


@router.post("/patients/{code}/revoke")
def revoke_patient(code: str, reason: str = Form(default="revoked by admin"),
                   _csrf=Depends(require_csrf), admin=Depends(require_admin),
                   session: Session = Depends(get_session)):
    """Revoking is the emergency switch: the kiosk deletes the patient on the next pull."""
    patient = session.get(Patient, code)
    if patient is not None:
        patient.revoked_at = dt.datetime.now(dt.timezone.utc)
        patient.revoke_reason = reason
        session.merge(Revocation(patient_code=code, reason=reason,
                                 revoked_at=dt.datetime.now(dt.timezone.utc)))
        for appointment in session.query(Appointment).filter(
                Appointment.patient_code == code).all():
            bump_gallery_version(session, appointment.procedure_date)
        session.commit()
    return RedirectResponse("/admin/patients", status_code=303)


@router.get("/appointments", response_class=HTMLResponse)
def appointments_page(request: Request, date: str = None, imported: int = None,
                      error: str = None, admin=Depends(require_admin),
                      session: Session = Depends(get_session)):
    date = date or dt.date.today().isoformat()
    rows = (session.query(Appointment, Patient)
            .join(Patient, Patient.patient_code == Appointment.patient_code)
            .filter(Appointment.procedure_date == date)
            .order_by(Patient.full_name).all())
    return render(request, "appointments.html", rows=rows, date=date, imported=imported,
                  error=error, columns=CSV_COLUMNS)


def parse_appointments_csv(data):
    """(rows, errors). Nothing is written unless every row parses."""
    text = data.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing:
        return [], ["missing columns: {}".format(", ".join(missing))]
    rows, errors = [], []
    for number, row in enumerate(reader, start=2):
        if not row.get("patient_code") or not row.get("full_name"):
            errors.append("line {}: patient_code and full_name are required".format(number))
            continue
        birth_year = (row.get("birth_year") or "").strip()
        if birth_year and not birth_year.isdigit():
            errors.append("line {}: birth_year '{}' is not a number".format(number, birth_year))
            continue
        rows.append({"patient_code": row["patient_code"].strip(),
                     "full_name": row["full_name"].strip(),
                     "birth_year": int(birth_year) if birth_year else None,
                     "appointment_code": (row.get("appointment_code") or "").strip() or None,
                     "procedure_date": (row.get("procedure_date") or "").strip()})
    return rows, errors


@router.post("/appointments/import")
async def import_appointments(request: Request, file: UploadFile,
                              _csrf=Depends(require_csrf), admin=Depends(require_admin),
                              session: Session = Depends(get_session)):
    rows, errors = parse_appointments_csv(await file.read())
    if errors:
        return RedirectResponse("/admin/appointments?error=" + "; ".join(errors)[:200],
                                status_code=303)
    dates = set()
    for row in rows:
        patient = session.get(Patient, row["patient_code"])
        if patient is None:
            session.add(Patient(patient_code=row["patient_code"], full_name=row["full_name"],
                                birth_year=row["birth_year"]))
        else:
            patient.full_name = row["full_name"]
            patient.birth_year = row["birth_year"] or patient.birth_year
        if row["appointment_code"]:
            date = row["procedure_date"] or dt.date.today().isoformat()
            appointment = session.get(Appointment, row["appointment_code"])
            if appointment is None:
                session.add(Appointment(appointment_code=row["appointment_code"],
                                        patient_code=row["patient_code"],
                                        procedure_date=date))
            else:
                appointment.patient_code = row["patient_code"]
                appointment.procedure_date = date
            dates.add(date)
    for date in dates:
        bump_gallery_version(session, date)
    session.commit()
    return RedirectResponse("/admin/appointments?imported={}".format(len(rows)),
                            status_code=303)


@router.get("/sessions", response_class=HTMLResponse)
def sessions_page(request: Request, decision: str = "", days: int = 7,
                  admin=Depends(require_admin), session: Session = Depends(get_session)):
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    query = session.query(SessionLog).filter(SessionLog.started_at >= since)
    if decision:
        query = query.filter(SessionLog.decision == decision)
    rows = query.order_by(SessionLog.started_at.desc()).limit(500).all()
    return render(request, "sessions.html", rows=rows, decision=decision, days=days)


@router.get("/sessions.csv")
def sessions_csv(days: int = 7, admin=Depends(require_admin),
                 session: Session = Depends(get_session)):
    """The operational metrics of spec §5 are computed from this export."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    rows = session.query(SessionLog).filter(SessionLog.started_at >= since).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["session_id", "device_id", "kind", "started_at", "decision", "rule_id",
                     "top1_code", "top1_score", "votes", "n_good_frames", "spoof_frames",
                     "nurse_action", "confirmed_code"])
    for row in rows:
        writer.writerow([row.session_id, row.device_id, row.kind,
                         row.started_at.isoformat() if row.started_at else "",
                         row.decision, row.rule_id, row.top1_code, row.top1_score, row.votes,
                         row.n_good_frames, row.spoof_frames, row.nurse_action,
                         row.confirmed_code])
    return Response(buffer.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sessions.csv"})


@router.get("/spoof", response_class=HTMLResponse)
def spoof_page(request: Request, admin=Depends(require_admin),
               session: Session = Depends(get_session)):
    rows = session.query(SpoofEvent).order_by(SpoofEvent.received_at.desc()).limit(200).all()
    return render(request, "spoof.html", rows=rows)


@router.get("/devices", response_class=HTMLResponse)
def devices_page(request: Request, token: str = None, admin=Depends(require_admin),
                 session: Session = Depends(get_session)):
    return render(request, "devices.html", devices=session.query(Device).all(), token=token)


@router.post("/devices")
def create_device(request: Request, device_id: str = Form(...), name: str = Form(...),
                  _csrf=Depends(require_csrf), admin=Depends(require_admin),
                  session: Session = Depends(get_session)):
    from server.db import hash_token, new_token

    token = new_token()
    session.merge(Device(device_id=device_id, name=name, token_hash=hash_token(token)))
    session.commit()
    # Shown once: the server only keeps the hash.
    return RedirectResponse("/admin/devices?token=" + token, status_code=303)
