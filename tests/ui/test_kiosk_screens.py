# -*- coding: utf-8 -*-
"""Offscreen smoke test: drive the real window through every scenario.

Marked `ui` because it needs PyQt5. It runs headless (QT_QPA_PLATFORM=offscreen), so CI
and a dev machine without a display can still catch a screen that fails to render.
"""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.ui
pytest.importorskip("PyQt5")

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.kiosk import view_model as vm  # noqa: E402
from edgeface.storage import db, kiosk_ipc, operators, patients  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts"))


@pytest.fixture(scope="module")
def qt_app():
    from PyQt5 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def cfg(tmp_path):
    base = cfg_mod.load_config(os.path.join(REPO, "configs", "dev.yaml"))
    merged = dict(base)
    merged["storage"] = dict(base["storage"], db_path=str(tmp_path / "edge.db"))
    merged["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "preview.jpg"))
    return merged


@pytest.fixture
def kiosk(qt_app, cfg):
    from edgeface.kiosk.__main__ import build

    _app, window, controller = build(cfg, fullscreen=False)
    window.resize(1024, 600)
    # Shown even offscreen: Qt reports every child of a hidden window as invisible, so
    # isVisible() assertions would be meaningless otherwise.
    window.show()
    yield window, controller
    window.close()
    controller.conn.close()


def publish(conn, state, guidance=None, payload=None, at=1000.0):
    with db.transaction(conn):
        kiosk_ipc.publish_state(conn, state, guidance, "s1", payload, at)


def rendered_text(window):
    from PyQt5 import QtWidgets

    page = window.stack.currentWidget()
    return " | ".join(w.text() for w in page.findChildren(QtWidgets.QLabel) if w.text())


@pytest.mark.parametrize("scenario_name", ["identify", "spoof", "low_quality", "enroll",
                                           "camera_error"])
def test_every_scenario_renders(kiosk, scenario_name):
    """Play a whole scenario at full speed; no step may fail to draw."""
    import fake_engine

    window, controller = kiosk
    scenario = fake_engine.load_scenario(scenario_name)
    for step in scenario["steps"]:
        step["hold"] = 0
    fake_engine.play(controller.conn, scenario, speed=1000, verbose=False)
    window.refresh()
    assert window.stack.currentWidget() is not None
    assert rendered_text(window)


def test_idle_then_guidance_then_candidate(kiosk):
    window, controller = kiosk
    with db.transaction(controller.conn):
        patients.upsert_patient(controller.conn, "BN001", "Nguyễn Thị Hà", 1990, "kiosk", 1000.0)

    publish(controller.conn, "IDLE")
    window.refresh()
    assert "Vui lòng đứng vào khung hình" in rendered_text(window)

    publish(controller.conn, "GUIDING", "STEP_CLOSER")
    window.refresh()
    assert "Vui lòng đứng gần hơn" in rendered_text(window)
    assert window.stack.currentWidget().preview.isVisible()

    publish(controller.conn, "AWAIT_NURSE", None, {
        "decision": "review_required", "rule_id": "R3",
        "candidate": {"code": "BN001", "score": 0.81, "margin": 0.2, "votes": 5, "k": 5}})
    window.refresh()
    text = rendered_text(window)
    assert "Nguyễn Thị Hà" in text and "BN001" in text
    assert "0.81" not in text          # the raw score never reaches the screen


def test_tapping_confirm_sends_the_command(kiosk):
    from PyQt5 import QtWidgets

    window, controller = kiosk
    publish(controller.conn, "AWAIT_NURSE", None, {
        "decision": "review_required",
        "candidate": {"code": "BN001", "score": 0.8, "margin": 0.2, "votes": 5, "k": 5}})
    window.refresh()
    page = window.stack.currentWidget()
    buttons = [b for b in page.findChildren(QtWidgets.QPushButton) if b.text() == "Xác nhận"]
    assert buttons, "the candidate card must offer a confirm button"
    buttons[0].click()

    commands = kiosk_ipc.claim_commands(controller.conn, at=1001.0)
    assert [c["type"] for c in commands] == ["confirm"]


def test_pin_pad_unlocks_the_admin_screen(kiosk):
    from PyQt5 import QtWidgets

    window, controller = kiosk
    with db.transaction(controller.conn):
        operators.create(controller.conn, "Nurse A", "123456", iterations=1000, at=1000.0)
    controller.open_pin()
    window.refresh()
    page = window.stack.currentWidget()
    keys = {b.text(): b for b in page.findChildren(QtWidgets.QPushButton)}
    for digit in "123456":
        keys[digit].click()
    assert controller.auth.is_unlocked() is True
    window.refresh()
    assert window.stack.currentWidget() is window.pages[vm.ADMIN]


def test_engine_silence_shows_the_error_screen(kiosk):
    window, controller = kiosk
    publish(controller.conn, "GUIDING", "STEP_CLOSER", at=1000.0)
    controller.poll(1000.0)
    view = controller.view(1000.0 + 60)     # no updates for a minute
    assert view.screen == vm.ERROR
