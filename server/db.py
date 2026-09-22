"""Engine, session factory and the small helpers the API and the web UI share."""
import contextlib
import hashlib
import secrets

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.models import Base, Device, GalleryVersion
from server.settings import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all():
    Base.metadata.create_all(engine)


@contextlib.contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def hash_token(token):
    """Device tokens are stored hashed: a database leak must not yield usable tokens."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token():
    return secrets.token_urlsafe(32)


def device_for_token(session: Session, token):
    if not token:
        return None
    return session.query(Device).filter(
        Device.token_hash == hash_token(token), Device.active.is_(True)).one_or_none()


def bump_gallery_version(session: Session, procedure_date):
    """Called whenever that day's patients, templates or revocations change."""
    row = session.get(GalleryVersion, procedure_date)
    if row is None:
        row = GalleryVersion(procedure_date=procedure_date, version=1)
        session.add(row)
    else:
        row.version += 1
    session.flush()
    return row.version
