"""Two kinds of caller: a device with a bearer token, and an admin with a cookie."""
import binascii
import datetime as dt
import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from server.db import device_for_token, get_session
from server.models import Admin

bearer = HTTPBearer(auto_error=False)

# PBKDF2-HMAC-SHA256 from the standard library, same scheme and format as the nurse PINs
# on the device (storage/operators.py). passlib + bcrypt 4.x raise on their own version
# probe, and a password hash is not worth a dependency that breaks on a minor upgrade.
PBKDF2_ITERATIONS = 240000
_ALGO = "pbkdf2_sha256"


def require_device(credentials: HTTPAuthorizationCredentials = Depends(bearer),
                   session: Session = Depends(get_session)):
    """The device token identifies the kiosk. No token, no data."""
    token = credentials.credentials if credentials else None
    device = device_for_token(session, token)
    if device is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="invalid device token",
                            headers={"WWW-Authenticate": "Bearer"})
    return device


def hash_password(password, iterations=PBKDF2_ITERATIONS, salt=None):
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "{}${}${}${}".format(_ALGO, iterations, binascii.hexlify(salt).decode(),
                                binascii.hexlify(digest).decode())


def verify_password(password, hashed):
    try:
        algo, iterations, salt_hex, hash_hex = hashed.split("$")
    except (ValueError, AttributeError):
        return False
    if algo != _ALGO:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 binascii.unhexlify(salt_hex), int(iterations))
    return hmac.compare_digest(binascii.hexlify(digest).decode(), hash_hex)


def current_admin(request: Request, session: Session = Depends(get_session)):
    username = request.session.get("admin")
    if not username:
        return None
    return session.get(Admin, username)


def require_admin(request: Request, session: Session = Depends(get_session)):
    admin = current_admin(request, session)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER,
                            headers={"Location": "/admin/login"})
    return admin


def touch_device(session, device, **fields):
    for key, value in fields.items():
        if value is not None:
            setattr(device, key, value)
    device.last_seen_at = dt.datetime.now(dt.timezone.utc)
