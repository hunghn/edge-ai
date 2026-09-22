# -*- coding: utf-8 -*-
"""Render every kiosk screen to a PNG, offscreen, for review and for the report.

  QT_QPA_PLATFORM=offscreen python tools/viz/kiosk_screens.py --out docs/figures/kiosk
"""
import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.kiosk import view_model as vm  # noqa: E402
from edgeface.kiosk.controller import KioskController  # noqa: E402
from edgeface.storage import clock, db, kiosk_ipc, operators, patients  # noqa: E402

SIZE = (1024, 600)      # 7" touchscreen; D-25 will confirm the real panel


def publish(conn, state, guidance=None, payload=None):
    with db.transaction(conn):
        kiosk_ipc.publish_state(conn, state, guidance, "demo", payload, clock.now())


def seed(conn):
    now = clock.now()
    with db.transaction(conn):
        patients.upsert_patient(conn, "BN001", "Nguyễn Thị Hà", 1990, "kiosk", now)
        patients.upsert_appointment(conn, "AP001", "BN001", clock.local_date(now))
        patients.upsert_patient(conn, "BN002", "Trần Văn Bình", 1985, "server", now)
        patients.upsert_appointment(conn, "AP002", "BN002", clock.local_date(now))
        operators.create(conn, "Điều dưỡng A", "123456", iterations=1000, at=now)


def shoot(window, path):
    from PyQt5 import QtWidgets

    QtWidgets.QApplication.processEvents()
    window.grab().save(path)
    print("wrote", path)


def main():
    from PyQt5 import QtWidgets  # noqa: F401  (imported for its side effect on the app)

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "figures", "kiosk"))
    ap.add_argument("--db", default=os.path.join(REPO, "var", "kiosk_demo.db"))
    args = ap.parse_args()
    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(args.db + suffix):
            os.remove(args.db + suffix)

    cfg = dict(cfg_mod.load_config(os.path.join(REPO, "configs", "dev.yaml")))
    cfg["storage"] = dict(cfg["storage"], db_path=args.db)

    from edgeface.kiosk.__main__ import build

    app, window, controller = build(cfg, fullscreen=False)
    window.resize(*SIZE)
    window.show()
    seed(controller.conn)

    candidate = {"code": "BN001", "score": 0.81, "margin": 0.22, "votes": 5, "k": 5}
    screens = [
        ("01_idle", lambda: publish(controller.conn, "IDLE")),
        ("02_guidance", lambda: publish(controller.conn, "GUIDING", "STEP_CLOSER")),
        ("03_candidate", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "review_required", "rule_id": "R3", "candidate": candidate,
            "timeout_at": clock.now() + 30})),
        ("04_spoof", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "spoof_suspect", "rule_id": "R1", "candidate": candidate})),
        ("05_low_quality", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "low_quality", "rule_id": "R2"})),
        ("08_enroll_progress", lambda: publish(controller.conn, "ENROLL_COLLECTING", None,
                                               {"progress": 3, "total": 5})),
        ("09_enroll_review", lambda: publish(controller.conn, "ENROLL_REVIEW", None, {
            "n_templates": 5, "warnings": ["duplicate_unknown_threshold"],
            "duplicate_code": "BN002", "self_consistency": 0.97})),
        ("11_camera_error", lambda: publish(controller.conn, "CAMERA_ERROR")),
    ]
    for name, action in screens:
        action()
        window.refresh()
        shoot(window, os.path.join(args.out, name + ".png"))

    # Screens the kiosk opens itself.
    publish(controller.conn, "AWAIT_NURSE", None, {"decision": "low_quality"})
    window.refresh()
    controller.open_search()
    controller.search("")
    controller.local_context["results"] = patients.list_active(controller.conn)
    window.refresh()
    shoot(window, os.path.join(args.out, "06_search.png"))

    controller.open_pin()
    window.refresh()
    shoot(window, os.path.join(args.out, "07_pin.png"))

    operator_id = controller.auth.operators()[0]["operator_id"]
    controller.open_admin_tab(vm.ADMIN)
    controller.unlock(operator_id, "123456")
    window.refresh()
    shoot(window, os.path.join(args.out, "10a_admin.png"))
    controller.open_admin_tab(vm.STATUS)
    window.refresh()
    shoot(window, os.path.join(args.out, "10b_status.png"))
    controller.open_admin_tab(vm.PATIENTS)
    window.refresh()
    shoot(window, os.path.join(args.out, "10c_patients.png"))

    window.open_enroll_form()
    shoot(window, os.path.join(args.out, "08a_enroll_form.png"))
    controller.conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
