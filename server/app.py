"""FastAPI application: device API under /api/v1, admin web UI under /admin."""
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from server.api import devices, events, gallery
from server.db import create_all
from server.settings import settings
from server.web import views


def create_app():
    app = FastAPI(title="edgeface server", version="1.0")
    app.add_middleware(SessionMiddleware, secret_key=settings.secret_key,
                       https_only=False, same_site="lax")
    app.include_router(events.router)
    app.include_router(gallery.router)
    app.include_router(devices.router)
    app.include_router(views.router)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/admin/")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True}

    create_all()
    return app


app = create_app()
