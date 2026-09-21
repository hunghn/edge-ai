"""Structured-ish logging to stderr; journald captures it under systemd."""
import logging
import os
import sys

_FMT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def get_logger(name):
    root = logging.getLogger("edgeface")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(_FMT))
        root.addHandler(handler)
        root.setLevel(os.environ.get("EDGEFACE_LOG_LEVEL", "INFO"))
    return root.getChild(name)
