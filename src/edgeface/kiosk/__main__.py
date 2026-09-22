# -*- coding: utf-8 -*-
"""Kiosk process.

    python3 -m edgeface.kiosk --config configs/nano.yaml
    python3 -m edgeface.kiosk --config configs/dev.yaml --windowed   # development
"""
import argparse
import os
import sys

from edgeface import config as cfg_mod
from edgeface.common.log import get_logger
from edgeface.kiosk.controller import KioskController
from edgeface.storage import db

LOG = get_logger("kiosk.main")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def build(cfg, fullscreen=True):
    """(app, window, controller) — separated so tests can drive it offscreen."""
    from PyQt5 import QtWidgets

    from edgeface.kiosk.window import KioskWindow

    db_path = cfg["storage"]["db_path"]
    conn = db.open_db(db_path if os.path.isabs(db_path) else os.path.join(REPO, db_path))
    controller = KioskController(conn, cfg)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    window = KioskWindow(controller, cfg, fullscreen=fullscreen)
    return app, window, controller


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    ap.add_argument("--windowed", action="store_true", help="do not go fullscreen")
    args = ap.parse_args(argv)

    cfg = cfg_mod.load_config(args.config)
    app, window, _controller = build(cfg, fullscreen=not args.windowed)
    LOG.info("kiosk started (%s)", "windowed" if args.windowed else "fullscreen")
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
