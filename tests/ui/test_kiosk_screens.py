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


def _scenario_names():
    """Every scenario on disk, so a new one is covered the moment it is written."""
    import fake_engine

    return sorted(fake_engine.list_scenarios())


@pytest.mark.parametrize("scenario_name", _scenario_names())
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
    assert "0.81" in text and "0.20" in text      # score and gap to the runner-up
    assert "%" not in text                        # a cosine is not a probability
    assert window.stack.currentWidget().preview.isVisible()


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


def buttons_of(window):
    """Every button label on the page currently shown."""
    from PyQt5 import QtWidgets

    page = window.stack.currentWidget()
    return {b.text(): b for b in page.findChildren(QtWidgets.QPushButton)}


def tap_row(list_widget, index):
    """A real tap on a list row.

    Emitting itemClicked by hand would hand Qt a QListWidgetItem that Python owns, and the
    handler rebuilds the list, so the item can be freed while the signal is still being
    delivered. Clicking the pixels avoids that and is what the nurse's finger does.
    """
    from PyQt5 import QtCore, QtTest

    item = list_widget.item(index)
    centre = list_widget.visualItemRect(item).center()
    QtTest.QTest.mouseClick(list_widget.viewport(), QtCore.Qt.LeftButton,
                            QtCore.Qt.NoModifier, centre)


def enrol_patient(controller, code="BN001", name="Nguyễn Thị Hà"):
    """A patient the admin screens can actually list.

    Created at the real clock, not the 1000.0 the state rows use: list_active() filters on
    the 24 h TTL, and a patient stamped 1970 would already have expired.
    """
    from edgeface.storage import clock

    with db.transaction(controller.conn):
        patients.upsert_patient(controller.conn, code, name, 1990, "kiosk", clock.now())


def enter_admin(window, controller, pin="123456"):
    with db.transaction(controller.conn):
        operators.create(controller.conn, "Nurse A", pin, iterations=1000, at=1000.0)
    controller.open_pin()
    window.refresh()
    keys = buttons_of(window)
    for digit in pin:
        keys[digit].click()
    window.refresh()
    return window.stack.currentWidget()


def test_admin_menu_opens_each_screen_by_tapping(kiosk):
    """Walk the nurse's actual path: taps only, no controller calls.

    The test this replaces asserted that the admin screen was reached and stopped there,
    so it stayed green while every one of these entries was missing and the screen was a
    dead end in the clinic.
    """
    window, controller = kiosk
    enter_admin(window, controller)
    labels = buttons_of(window)
    for expected in ("Đăng ký bệnh nhân mới", "Bệnh nhân hôm nay",
                     "Trạng thái hệ thống", "Đổi PIN", "Thoát quản trị"):
        assert expected in labels, "admin menu is missing {}".format(expected)

    # Enrolment: the form, with the four fields a nurse has to fill in.
    labels["Đăng ký bệnh nhân mới"].click()
    assert window.stack.currentWidget() is window.enroll_form
    assert set(window.enroll_form.inputs) == {"patient_code", "full_name", "birth_year",
                                              "appointment_code"}
    buttons_of(window)["Huỷ"].click()

    # Today's patients, with a real row in it.
    enrol_patient(controller)
    buttons_of(window)["Bệnh nhân hôm nay"].click()
    page = window.stack.currentWidget()
    assert page is window.pages[vm.PATIENTS]
    assert page.rows.count() == 1 and "BN001" in page.rows.item(0).text()
    buttons_of(window)["Quay lại menu"].click()

    # System status: the rows must carry values, not just labels.
    buttons_of(window)["Trạng thái hệ thống"].click()
    assert window.stack.currentWidget() is window.pages[vm.STATUS]
    assert "Phiên bản gallery" in rendered_text(window)
    buttons_of(window)["Quay lại menu"].click()

    # Change PIN.
    buttons_of(window)["Đổi PIN"].click()
    assert window.stack.currentWidget() is window.pages[vm.CHANGE_PIN]
    assert "Nhập mã PIN hiện tại" in rendered_text(window)
    buttons_of(window)["Quay lại menu"].click()

    assert window.stack.currentWidget() is window.pages[vm.ADMIN]


def test_enrolment_form_sends_the_command_to_the_engine(kiosk):
    window, controller = kiosk
    enter_admin(window, controller)
    buttons_of(window)["Đăng ký bệnh nhân mới"].click()
    form = window.enroll_form
    form.inputs["patient_code"].setText("BN042")
    form.inputs["full_name"].setText("Trần Văn B")
    form.inputs["birth_year"].setText("1988")
    buttons_of(window)["Bắt đầu chụp"].click()

    command = kiosk_ipc.claim_commands(controller.conn, at=1001.0)[0]
    assert command["type"] == "start_enroll"
    assert command["payload"]["patient_code"] == "BN042"
    assert command["payload"]["birth_year"] == 1988


def test_tapping_a_patient_then_revoke_removes_them(kiosk):
    window, controller = kiosk
    enter_admin(window, controller)
    enrol_patient(controller)
    buttons_of(window)["Bệnh nhân hôm nay"].click()
    page = window.stack.currentWidget()

    assert "Thu hồi" not in buttons_of(window)       # nothing selected yet
    tap_row(page.rows, 0)
    window.refresh()
    buttons_of(window)["Thu hồi"].click()
    # Deleting a patient's face data is not something one tap should do, so the page
    # asks first and the answer is a different button.
    assert patients.get(controller.conn, "BN001") is not None
    buttons_of(window)["Xoá khỏi máy này"].click()

    assert patients.get(controller.conn, "BN001") is None
    assert "BN001" in rendered_text(window)


def test_engine_silence_shows_the_error_screen(kiosk):
    window, controller = kiosk
    publish(controller.conn, "GUIDING", "STEP_CLOSER", at=1000.0)
    controller.poll(1000.0)
    view = controller.view(1000.0 + 60)     # no updates for a minute
    assert view.screen == vm.ERROR


def test_enrolment_runs_from_the_form_to_the_saved_patient(kiosk):
    """The whole enrolment path, tap by tap, the way a nurse walks it.

    The form is only the first of five screens: it hands over to the engine, which guides
    the patient, counts the shots and then asks the nurse to save.
    """
    window, controller = kiosk
    enter_admin(window, controller)
    buttons_of(window)["Đăng ký bệnh nhân mới"].click()
    window.enroll_form.inputs["patient_code"].setText("BN042")
    window.enroll_form.inputs["full_name"].setText("Trần Văn B")
    buttons_of(window)["Bắt đầu chụp"].click()
    assert kiosk_ipc.claim_commands(controller.conn, at=1001.0)[0]["type"] == "start_enroll"

    # The engine takes over: the form must give way to the live guidance screen.
    publish(controller.conn, "ENROLL_GUIDING", "STEP_CLOSER", {"progress": 0, "total": 5})
    window.refresh()
    assert window.stack.currentWidget() is not window.enroll_form
    assert "Vui lòng đứng gần hơn" in rendered_text(window)

    publish(controller.conn, "ENROLL_COLLECTING", None, {"progress": 3, "total": 5})
    window.refresh()
    assert "Đã chụp 3/5" in rendered_text(window)

    # Five shots taken: the nurse gets the save button.
    publish(controller.conn, "ENROLL_REVIEW", None, {"n_templates": 5})
    window.refresh()
    assert "Lưu bệnh nhân" in buttons_of(window)
    buttons_of(window)["Lưu bệnh nhân"].click()
    assert kiosk_ipc.claim_commands(controller.conn, at=1002.0)[0]["type"] == "enroll_confirm"


def test_identification_card_offers_every_nurse_action(kiosk):
    """The identify screen, tap by tap: each of the four buttons must reach the engine."""
    window, controller = kiosk
    enrol_patient(controller)

    for label, expected in (("Xác nhận", "confirm"), ("Không phải", "reject"),
                            ("Thử lại", "retry")):
        publish(controller.conn, "AWAIT_NURSE", None, {
            "decision": "review_required", "rule_id": "R3",
            "candidate": {"code": "BN001", "score": 0.8, "margin": 0.1, "votes": 5, "k": 5}})
        window.refresh()
        assert window.stack.currentWidget() is window.pages[vm.CANDIDATE]
        text = rendered_text(window)
        assert "BN001" in text and "Nguyễn Thị Hà" in text
        assert "Cần kiểm tra" in text          # thresholds are null: never "Khớp cao"
        buttons_of(window)[label].click()
        sent = kiosk_ipc.claim_commands(controller.conn, at=1001.0)
        assert [c["type"] for c in sent] == [expected], label


def test_manual_search_picks_a_patient_by_hand(kiosk):
    window, controller = kiosk
    enrol_patient(controller)
    publish(controller.conn, "AWAIT_NURSE", None, {
        "decision": "review_required",
        "candidate": {"code": "BN001", "score": 0.8, "margin": 0.1, "votes": 5, "k": 5}})
    window.refresh()

    buttons_of(window)["Tìm thủ công"].click()
    page = window.stack.currentWidget()
    assert page is window.pages[vm.SEARCH]
    page.search_box.setText("Hà")             # accent-insensitive lookup
    window.refresh()
    assert page.results.count() == 1
    tap_row(page.results, 0)

    command = kiosk_ipc.claim_commands(controller.conn, at=1001.0)[0]
    assert command["type"] == "manual" and command["payload"]["code"] == "BN001"


def test_a_spoof_suspect_raises_the_alarm_screen(kiosk):
    window, controller = kiosk
    publish(controller.conn, "AWAIT_NURSE", None, {"decision": "spoof_suspect"})
    window.refresh()
    assert window.stack.currentWidget() is window.pages[vm.ALERT]
    # No confirm button on this screen: a suspected presentation attack is never
    # something the nurse can wave through with one tap.
    assert "Xác nhận" not in buttons_of(window)
    assert "Thử lại" in buttons_of(window)


def test_low_quality_asks_for_another_try(kiosk):
    window, controller = kiosk
    publish(controller.conn, "AWAIT_NURSE", None, {"decision": "low_quality"})
    window.refresh()
    assert window.stack.currentWidget() is window.pages[vm.ALERT]
    assert "Thử lại" in buttons_of(window)


def test_the_screen_is_not_rebuilt_on_every_redraw(kiosk):
    """Widgets must survive a redraw, or no click on the device ever completes.

    A click is a press and a release, and the window redraws ten times a second. Destroy
    the button in between and Qt drops the mouse grab, so the release reaches nothing and
    the click is lost - which is why only the PIN pad, the one row of buttons that is
    built once instead of per render, worked on the kiosk.

    QTest cannot express this: its synthetic release is delivered straight to the widget
    object, grab or no grab, so a press/redraw/release test passes either way. Widget
    identity across redraws is the property that actually matters, so that is what this
    asserts.
    """
    window, controller = kiosk
    enter_admin(window, controller)
    before = buttons_of(window)["Đăng ký bệnh nhân mới"]
    for _ in range(5):
        window.refresh()
    assert buttons_of(window)["Đăng ký bệnh nhân mới"] is before

    # The same for the candidate card, the screen a nurse touches on every patient.
    controller.logout()
    publish(controller.conn, "AWAIT_NURSE", None, {
        "decision": "review_required",
        "candidate": {"code": "BN001", "score": 0.8, "margin": 0.1, "votes": 5, "k": 5}})
    window.refresh()
    confirm = buttons_of(window)["Xác nhận"]
    for _ in range(5):
        window.refresh()
    assert buttons_of(window)["Xác nhận"] is confirm


def test_search_results_survive_a_redraw(kiosk):
    """Same hazard on the manual lookup list: the nurse taps a row, not a button."""
    window, controller = kiosk
    enrol_patient(controller)
    publish(controller.conn, "AWAIT_NURSE", None, {"decision": "low_quality"})
    window.refresh()
    buttons_of(window)["Tìm thủ công"].click()
    page = window.stack.currentWidget()
    page.search_box.setText("Hà")
    window.refresh()
    row = page.results.item(0)
    for _ in range(5):
        window.refresh()
    assert page.results.item(0) is row


def _enrol_with_face(controller, code, name, pixel):
    """A patient who has a stored enrolment crop."""
    import numpy as np
    from edgeface.storage import clock, faces

    with db.transaction(controller.conn):
        patients.upsert_patient(controller.conn, code, name, 1990, "kiosk", clock.now())
        faces.save(controller.conn, code,
                   faces.encode(np.full((112, 112, 3), pixel, dtype=np.uint8)), clock.now())


def _publish_duplicates(controller, entries):
    publish(controller.conn, "ENROLL_REVIEW", None, {
        "n_templates": 5, "warnings": ["duplicate_unknown_threshold"],
        "duplicates": [{"code": code, "score": score} for code, score in entries]})


def test_the_duplicate_warning_shows_a_face_per_patient(kiosk):
    window, controller = kiosk
    _enrol_with_face(controller, "BN000201", "Nguyễn Thị Hà", 40)
    _enrol_with_face(controller, "BN000147", "Trần Văn B", 200)
    _publish_duplicates(controller, [("BN000201", 0.91), ("BN000147", 0.88)])
    window.refresh()

    page = window.stack.currentWidget()
    assert page is window.pages[vm.DUPLICATE]
    assert page._rows_layout.count() == 2
    text = rendered_text(window)
    assert "BN****01" in text and "BN****47" in text
    assert "0.91" in text and "0.88" in text


def test_the_duplicate_warning_never_shows_the_other_patient_name(kiosk):
    """The face answers "is this the same person". The name is not the nurse's to read."""
    window, controller = kiosk
    _enrol_with_face(controller, "BN000201", "Nguyễn Thị Hà", 40)
    _publish_duplicates(controller, [("BN000201", 0.91)])
    window.refresh()

    text = rendered_text(window)
    assert "Nguyễn Thị Hà" not in text
    assert "BN000201" not in text          # the full code is masked too
    assert "***" in text


def test_a_patient_without_a_picture_keeps_its_own_row(kiosk):
    """Server-sourced patients have no crop. The row must still be theirs.

    A dict keyed by code would drop this patient and shift the pictures up, putting one
    person's face beside another person's code.
    """
    from edgeface.storage import clock

    window, controller = kiosk
    with db.transaction(controller.conn):        # no face for this one
        patients.upsert_patient(controller.conn, "BN000111", "A", 1990, "server", clock.now())
    _enrol_with_face(controller, "BN000222", "B", 200)
    _publish_duplicates(controller, [("BN000111", 0.95), ("BN000222", 0.80)])
    window.refresh()

    page = window.stack.currentWidget()
    assert controller.duplicate_faces()[0] is None       # the photoless patient, first
    assert controller.duplicate_faces()[1] is not None
    assert page._rows_layout.count() == 2
    assert "chưa có ảnh" in rendered_text(window)


def test_saving_anyway_reaches_the_engine(kiosk):
    """C-22: a duplicate is a warning, not a block - the nurse can still go ahead."""
    window, controller = kiosk
    _enrol_with_face(controller, "BN000201", "Nguyễn Thị Hà", 40)
    _publish_duplicates(controller, [("BN000201", 0.91)])
    window.refresh()

    # Both buttons say what they do: the safe way out is the one that is filled in,
    # and saving a second record for the same face is the one that has to be chosen.
    assert "Huỷ và tra mã cũ" in buttons_of(window)
    buttons_of(window)["Vẫn lưu hồ sơ mới"].click()
    sent = kiosk_ipc.claim_commands(controller.conn, at=1001.0)
    assert [c["type"] for c in sent] == ["enroll_confirm"]


# ---------------------------------------------------------------- the redesign
def test_the_rail_moves_between_admin_screens_without_going_back_to_a_menu(kiosk):
    """The point of the rail: four destinations, no walking back up between jobs."""
    window, controller = kiosk
    enter_admin(window, controller)
    enrol_patient(controller)

    page = window.pages[vm.ADMIN]
    page.rail.buttons["patients"].click()
    assert window.stack.currentWidget() is window.pages[vm.PATIENTS]

    window.pages[vm.PATIENTS].rail.buttons["status"].click()
    assert window.stack.currentWidget() is window.pages[vm.STATUS]

    window.pages[vm.STATUS].rail.buttons["logout"].click()
    assert controller.auth.is_unlocked() is False


def test_cancelling_the_revoke_dialog_keeps_the_patient(kiosk):
    window, controller = kiosk
    enter_admin(window, controller)
    enrol_patient(controller)
    buttons_of(window)["Bệnh nhân hôm nay"].click()
    page = window.stack.currentWidget()
    tap_row(page.rows, 0)
    buttons_of(window)["Thu hồi"].click()

    assert page.dialog.isVisible()
    buttons_of(window)["Huỷ"].click()
    assert not page.dialog.isVisible()
    assert patients.get(controller.conn, "BN001") is not None


def test_the_bin_on_a_row_asks_about_that_row(kiosk):
    """Tapping the bin is a delete; tapping anywhere else on the row is a selection."""
    from PyQt5 import QtCore, QtTest

    window, controller = kiosk
    enter_admin(window, controller)
    enrol_patient(controller)
    buttons_of(window)["Bệnh nhân hôm nay"].click()
    page = window.stack.currentWidget()

    item = page.rows.item(0)
    rect = page.rows.visualItemRect(item)
    bin_rect = page.rows.itemDelegate().trash_rect(rect)
    QtTest.QTest.mouseClick(page.rows.viewport(), QtCore.Qt.LeftButton,
                            QtCore.Qt.NoModifier, bin_rect.center())
    assert page.dialog.isVisible()
    assert "BN001" in rendered_text(window)


def test_the_keyboard_types_into_the_field_that_has_the_focus(kiosk, qt_app):
    """A touchscreen has no keys, so the form's four fields share one soft keyboard."""
    from PyQt5 import QtWidgets

    window, controller = kiosk
    enter_admin(window, controller)
    buttons_of(window)["Đăng ký bệnh nhân mới"].click()
    form = window.enroll_form

    form.inputs["patient_code"].setFocus()
    qt_app.processEvents()
    keys = {b.text(): b for b in form.keyboard.findChildren(QtWidgets.QPushButton)}
    keys["123"].click()
    keys = {b.text(): b for b in form.keyboard.findChildren(QtWidgets.QPushButton)}
    for digit in "13":
        keys[digit].click()
    assert form.inputs["patient_code"].text() == "13"
    assert form.inputs["full_name"].text() == ""

    form.inputs["full_name"].setFocus()
    qt_app.processEvents()
    keys = {b.text(): b for b in form.keyboard.findChildren(QtWidgets.QPushButton)}
    keys["ABC"].click()
    keys = {b.text(): b for b in form.keyboard.findChildren(QtWidgets.QPushButton)}
    keys["h"].click()
    assert form.inputs["full_name"].text() == "h"
    assert form.inputs["patient_code"].text() == "13"


def candidate_payload():
    return {"decision": "review_required", "rule_id": "R3",
            "candidate": {"code": "BN001", "score": 0.8, "margin": 0.1, "votes": 5,
                          "k": 5}}


def test_the_answer_is_the_last_button_on_the_row(kiosk):
    """Four buttons of equal weight made the nurse read all of them before choosing."""
    window, controller = kiosk
    publish(controller.conn, "AWAIT_NURSE", payload=candidate_payload())
    window.refresh()
    page = window.stack.currentWidget()

    row = page.actions.buttons
    labels = [row.itemAt(i).widget().text() for i in range(row.count())]
    assert labels[-1] == "Xác nhận"
    assert labels[-2] == "Không phải"
    assert row.itemAt(row.count() - 1).widget().objectName() == "primary"
    assert row.itemAt(row.count() - 2).widget().objectName() == "danger"


def test_the_new_pages_are_not_rebuilt_on_every_redraw(kiosk):
    """Same rule as the first version: a rebuild between press and release eats the tap."""
    window, controller = kiosk
    publish(controller.conn, "AWAIT_NURSE", payload=candidate_payload())
    window.refresh()
    page = window.stack.currentWidget()
    confirm = buttons_of(window)["Xác nhận"]
    avatar = page.avatar
    for _ in range(5):
        window.refresh()
    assert buttons_of(window)["Xác nhận"] is confirm
    assert page.avatar is avatar

    enter_admin(window, controller)
    enrol_patient(controller)
    buttons_of(window)["Trạng thái hệ thống"].click()
    status = window.stack.currentWidget()
    tiles = list(status.tiles)
    for _ in range(5):
        window.refresh()
    assert list(status.tiles) == tiles
