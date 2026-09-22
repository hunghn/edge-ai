"""CSRF tokens for the admin forms.

The session cookie is SameSite=lax, which already blocks cross-site POSTs in current
browsers, but a revoke button is destructive enough to deserve a second lock that does
not depend on the browser's behaviour.
"""
import hmac
import secrets

from fastapi import Form, HTTPException, Request

FIELD = "csrf_token"


def token_for(request: Request):
    token = request.session.get(FIELD)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[FIELD] = token
    return token


def verify(request: Request, submitted):
    expected = request.session.get(FIELD)
    if not expected or not submitted or not hmac.compare_digest(expected, submitted):
        raise HTTPException(status_code=400, detail="invalid CSRF token")
    return True


def require_csrf(request: Request, csrf_token: str = Form(default="")):
    """FastAPI dependency for every state-changing admin form."""
    return verify(request, csrf_token)
