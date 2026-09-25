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
from edgeface.storage import (clock, db, faces, kiosk_ipc, operators,  # noqa: E402
                              patients, templates)

SIZE = (1024, 640)      # the wireframe ratio; D-25 will confirm the real panel


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
        # A face for one of them, so the duplicate warning has something to compare;
        # the other stays without one, which is what a server-pulled patient looks like.
        faces.save(conn, "BN001", _demo_face(), at=now)
        templates.add_templates(conn, "BN001", [_demo_embedding() for _ in range(5)],
                                "demo-sha", created_at=now)


def _demo_embedding():
    import numpy as np

    vector = np.zeros(512, dtype="float32")
    vector[0] = 1.0
    return vector


def _demo_face():
    """A flat grey crop. The figures are for layout review, not for face quality."""
    import numpy as np

    return faces.encode(np.full((112, 112, 3), 90, dtype=np.uint8))


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

    candidate = dict({"code": "BN001", "score": 0.81, "margin": 0.22, "votes": 5,
                      "k": 5}, top2_code="BN000247", top2_score=0.69)
    device = {"ram_mb": 2104, "ram_total_mb": 3956, "temp_c": 48, "cpu_pct": 37}
    screens = [
        ("01_idle", lambda: publish(controller.conn, "IDLE", None,
                                    {"device": device})),
        ("02_guidance", lambda: publish(controller.conn, "GUIDING", "STEP_CLOSER", {
            "telemetry": {"stage": "S2", "kept": 2, "need": 5, "fps": 12.4,
                          "det_score": 0.88}})),
        ("03_candidate", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "review_required", "rule_id": "R3", "candidate": candidate,
            "telemetry": {"quality": 0.91, "good": 5, "need": 5, "fps": 12.4},
            "timeout_at": clock.now() + 29})),
        ("04_spoof", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "spoof_suspect", "rule_id": "R1", "candidate": candidate,
            "telemetry": {"p_real": 0.41, "good": 0, "need": 5}})),
        ("05_low_quality", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "low_quality", "rule_id": "R2",
            "telemetry": {"blur": 41, "lum": 52, "yaw": 9, "good": 2, "need": 5}})),
        ("05b_no_match", lambda: publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "no_match", "rule_id": "R4", "candidate": None,
            "telemetry": {"quality": 0.88, "good": 5, "need": 5}})),
        ("08_enroll_progress", lambda: publish(controller.conn, "ENROLL_COLLECTING", None,
                                               {"progress": 3, "total": 5,
                                                "telemetry": {"kept": 3, "need": 5,
                                                              "fps": 13.1,
                                                              "quality": 0.9}})),
        ("09_enroll_review", lambda: publish(controller.conn, "ENROLL_REVIEW", None, {
            "n_templates": 5, "warnings": ["duplicate_unknown_threshold"],
            "duplicate_code": "BN002", "self_consistency": 0.97})),
        ("09b_duplicate", lambda: publish(controller.conn, "ENROLL_REVIEW", None, {
            "n_templates": 5, "warnings": ["duplicate_unknown_threshold"],
            "duplicate_code": "BN001", "duplicate_score": 0.81, "self_consistency": 0.96,
            "duplicates": [{"code": "BN001", "score": 0.81},
                           {"code": "BN002", "score": 0.74}]})),
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

    # The dialog that guards the one action a nurse cannot take back.
    page = window.pages[vm.PATIENTS]
    controller.select_patient("BN001")
    window.refresh()
    page._ask("BN001")
    shoot(window, os.path.join(args.out, "10d_revoke.png"))
    page.dialog.hide()

    controller.open_admin_tab(vm.CHANGE_PIN)
    controller.open_change_pin()
    controller.submit_change_pin("123456")
    window.refresh()
    shoot(window, os.path.join(args.out, "12_change_pin.png"))

    controller.open_admin_tab(vm.ADMIN)
    window.open_enroll_form()
    shoot(window, os.path.join(args.out, "08a_enroll_form.png"))
    controller.conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
