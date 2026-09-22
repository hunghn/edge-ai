"""Server configuration, from environment variables with usable defaults."""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Settings:
    database_url = os.environ.get("EDGEFACE_DB", "sqlite:///" + os.path.join(BASE_DIR, "server.db"))
    # Session cookie signing key. Generated per process when unset, which logs every
    # admin out on restart — fine for a demo, set it in production.
    secret_key = os.environ.get("EDGEFACE_SECRET", secrets.token_hex(32))
    bundle_dir = os.environ.get("EDGEFACE_BUNDLES", os.path.join(BASE_DIR, "bundles"))
    # HMAC key for signing model bundles (D-24). A device verifies with the same key.
    bundle_key_path = os.environ.get("EDGEFACE_BUNDLE_KEY",
                                     os.path.join(BASE_DIR, "bundle.key"))
    max_events_per_request = int(os.environ.get("EDGEFACE_MAX_EVENTS", "100"))
    gallery_page_limit = int(os.environ.get("EDGEFACE_GALLERY_LIMIT", "500"))


settings = Settings()
