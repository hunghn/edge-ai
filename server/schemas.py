"""Request/response models. Pydantic validates what the device sends before it lands."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventIn(BaseModel):
    event_id: str = Field(min_length=8, max_length=64)
    type: str
    created_at: float
    payload: Dict[str, Any] = Field(default_factory=dict)


class EventBatch(BaseModel):
    device_id: str
    events: List[EventIn]


class EventResult(BaseModel):
    accepted: List[str] = Field(default_factory=list)
    duplicate: List[str] = Field(default_factory=list)
    rejected: List[Dict[str, str]] = Field(default_factory=list)


class TemplateOut(BaseModel):
    embedding_b64: str
    quality: Optional[float] = None


class PatientOut(BaseModel):
    patient_code: str
    full_name: str
    birth_year: Optional[int] = None
    appointment_code: Optional[str] = None
    templates: List[TemplateOut] = Field(default_factory=list)


class GalleryOut(BaseModel):
    changed: bool = True
    date: str
    version: int
    recognizer_sha256: Optional[str] = None
    patients: List[PatientOut] = Field(default_factory=list)


class RevocationOut(BaseModel):
    patient_code: str
    revoked_at: float
    reason: Optional[str] = None


class BundleOut(BaseModel):
    version: str
    sha256: str
    signature: str
    size: Optional[int] = None
    url: str


class HeartbeatIn(BaseModel):
    gallery_version: Optional[int] = None
    model_version: Optional[str] = None
    disk_free_mb: Optional[float] = None
    outbox_pending: Optional[int] = None
    uptime_s: Optional[float] = None
