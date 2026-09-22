"""Server-side schema. SQLAlchemy 2.0 declarative; SQLite by default, Postgres by URL."""
import datetime as dt

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer, LargeBinary,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Device(Base):
    """One kiosk. The token is stored hashed; it is shown once at creation."""
    __tablename__ = "devices"
    device_id = Column(String(64), primary_key=True)
    name = Column(String(200), nullable=False)
    token_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    last_seen_at = Column(DateTime(timezone=True))
    last_gallery_version = Column(Integer)
    model_version = Column(String(64))
    active = Column(Boolean, default=True, nullable=False)


class Patient(Base):
    __tablename__ = "patients"
    patient_code = Column(String(64), primary_key=True)
    full_name = Column(String(200), nullable=False)
    birth_year = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    revoked_at = Column(DateTime(timezone=True))
    revoke_reason = Column(String(200))
    templates = relationship("FaceTemplate", back_populates="patient",
                             cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="patient",
                                cascade="all, delete-orphan")


class Appointment(Base):
    __tablename__ = "appointments"
    appointment_code = Column(String(64), primary_key=True)
    patient_code = Column(String(64), ForeignKey("patients.patient_code", ondelete="CASCADE"),
                          nullable=False, index=True)
    procedure_date = Column(String(10), nullable=False, index=True)   # YYYY-MM-DD
    status = Column(String(32), default="scheduled", nullable=False)
    patient = relationship("Patient", back_populates="appointments")


class FaceTemplate(Base):
    __tablename__ = "face_templates"
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_code = Column(String(64), ForeignKey("patients.patient_code", ondelete="CASCADE"),
                          nullable=False, index=True)
    embedding = Column(LargeBinary, nullable=False)        # 512 x float32 little endian
    quality = Column(Float)
    recognizer_sha256 = Column(String(64), nullable=False, index=True)
    source_device_id = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=utcnow)
    patient = relationship("Patient", back_populates="templates")


class Event(Base):
    """Raw inbox. event_id comes from the device and makes retries idempotent."""
    __tablename__ = "events"
    event_id = Column(String(64), primary_key=True)
    device_id = Column(String(64), index=True)
    type = Column(String(64), nullable=False, index=True)
    payload = Column(Text, nullable=False)
    received_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class SessionLog(Base):
    """Flattened session.closed events, so the web UI can query them."""
    __tablename__ = "sessions_log"
    session_id = Column(String(64), primary_key=True)
    device_id = Column(String(64), index=True)
    kind = Column(String(16))
    started_at = Column(DateTime(timezone=True), index=True)
    decision = Column(String(32), index=True)
    rule_id = Column(String(8))
    top1_code = Column(String(64))
    top1_score = Column(Float)
    votes = Column(Integer)
    n_good_frames = Column(Integer)
    spoof_frames = Column(Integer)
    nurse_action = Column(String(16), index=True)
    confirmed_code = Column(String(64))
    operator_id = Column(Integer)


class SpoofEvent(Base):
    __tablename__ = "spoof_events"
    event_id = Column(String(64), primary_key=True)
    device_id = Column(String(64), index=True)
    session_id = Column(String(64))
    min_p_real = Column(Float)
    spoof_frames = Column(Integer)
    evidence_sha256 = Column(String(64))
    received_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class GalleryVersion(Base):
    """One row per day: bumped whenever that day's gallery content changes."""
    __tablename__ = "gallery_versions"
    procedure_date = Column(String(10), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime(timezone=True), default=utcnow)


class Bundle(Base):
    __tablename__ = "bundles"
    version = Column(String(64), primary_key=True)
    file_path = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False)
    signature = Column(String(128), nullable=False)
    size = Column(Integer)
    active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Admin(Base):
    __tablename__ = "admins"
    username = Column(String(64), primary_key=True)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Revocation(Base):
    __tablename__ = "revocations"
    patient_code = Column(String(64), primary_key=True)
    revoked_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    reason = Column(String(200))
    __table_args__ = (UniqueConstraint("patient_code", name="uq_revocation_patient"),)
