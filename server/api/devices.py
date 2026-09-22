"""Device heartbeat: how the fleet page knows a kiosk is alive."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.auth import require_device, touch_device
from server.db import get_session
from server.schemas import HeartbeatIn

router = APIRouter(prefix="/api/v1", tags=["devices"])


@router.post("/devices/heartbeat")
def heartbeat(body: HeartbeatIn, device=Depends(require_device),
              session: Session = Depends(get_session)):
    touch_device(session, device, last_gallery_version=body.gallery_version,
                 model_version=body.model_version)
    session.commit()
    return {"ok": True, "server_time": __import__("time").time()}
