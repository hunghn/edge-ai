# -*- coding: utf-8 -*-
"""Kiosk controller: polling, nurse commands, manual search and the PIN gate."""
import os

import pytest

from edgeface import config as cfg_mod
from edgeface.kiosk import view_model as vm
from edgeface.kiosk.controller import KioskController
from edgeface.storage import clock, db, kiosk_ipc, operators, patients, templates

T0 = 1_700_000_000.0
FAST = 1000          # PBKDF2 rounds for the tests


@pytest.fixture
def cfg(repo_root, tmp_path):
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    merged = dict(base)
    merged["storage"] = dict(base["storage"], db_path=str(tmp_path / "edge.db"))
    merged["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "preview.jpg"))
    return merged


@pytest.fixture
def conn(cfg):
    c = db.open_db(cfg["storage"]["db_path"])
    yield c
    c.close()


@pytest.fixture
def kiosk(conn, cfg):
    return KioskController(conn, cfg)


def publish(conn, state, guidance=None, payload=None, at=T0):
    with db.transaction(conn):
        return kiosk_ipc.publish_state(conn, state, guidance, "s1", payload, at)


def add_patient(conn, code, name, at=T0):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, name, 1990, "kiosk", at)
        # Today's date, not a literal: the candidate card looks up the appointment for
        # the current day, so a hardcoded date turns the test into a time bomb.
        patients.upsert_appointment(conn, "AP-" + code, code, clock.local_date(clock.now()))


def test_poll_reports_only_changes(kiosk, conn):
    assert kiosk.poll(T0) is True           # the seeded IDLE row
    assert kiosk.poll(T0) is False
    publish(conn, "GUIDING", "STEP_CLOSER")
    assert kiosk.poll(T0) is True
    assert kiosk.view(T0).message == "Vui lòng đứng gần hơn"


def test_candidate_card_is_filled_from_the_local_record(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    publish(conn, "AWAIT_NURSE", payload={"decision": "review_required",
                                          "candidate": {"code": "BN001", "score": 0.8,
                                                        "margin": 0.1, "votes": 5, "k": 5}})
    kiosk.poll(T0)
    view = kiosk.view(T0)
    assert view.screen == vm.CANDIDATE
    assert dict(view.fields)["Họ và tên"] == "Nguyễn Thị Hà"
    assert dict(view.fields)["Mã lịch hôm nay"] == "AP-BN001"


def test_button_press_sends_the_command(kiosk, conn):
    publish(conn, "AWAIT_NURSE", payload={"decision": "review_required",
                                          "candidate": {"code": "BN001", "score": 0.8,
                                                        "margin": 0.1, "votes": 5, "k": 5}})
    kiosk.poll(T0)
    confirm = kiosk.view(T0).buttons[0]
    assert kiosk.on_button(confirm, T0) is True
    commands = kiosk_ipc.claim_commands(conn, at=T0 + 1)
    assert [c["type"] for c in commands] == ["confirm"]
    assert commands[0]["session_id"] == "s1"


def test_search_button_opens_a_local_screen_without_a_command(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    add_patient(conn, "BN002", "Trần Văn Bình")
    publish(conn, "AWAIT_NURSE", payload={"decision": "low_quality"})
    kiosk.poll(T0)
    search_button = [b for b in kiosk.view(T0).buttons if b.kind == "search"][0]
    kiosk.on_button(search_button, T0)
    assert kiosk.view(T0).screen == vm.SEARCH
    assert kiosk_ipc.pending_commands(conn) == 0        # nothing sent to the engine yet

    results = kiosk.search("nguyen", T0)
    assert [r["patient_code"] for r in results] == ["BN001"]
    assert kiosk.view(T0).fields == (("BN001", "Nguyễn Thị Hà"),)

    kiosk.choose_patient("BN001", T0)
    command = kiosk_ipc.claim_commands(conn, at=T0 + 1)[0]
    assert command["type"] == "manual" and command["payload"]["code"] == "BN001"
    assert kiosk.view(T0).screen != vm.SEARCH           # back to the engine's screen


def test_a_new_patient_closes_the_nurse_search_screen(kiosk, conn):
    publish(conn, "AWAIT_NURSE", payload={"decision": "low_quality"})
    kiosk.poll(T0)
    kiosk.open_search()
    publish(conn, "IDLE", at=T0 + 5)
    kiosk.poll(T0 + 5)
    assert kiosk.local_screen is None


def test_pin_gate_guards_the_admin_screens(kiosk, conn, cfg):
    with db.transaction(conn):
        operator_id = operators.create(conn, "Nurse A", "123456", iterations=FAST, at=T0)
    kiosk.poll(T0)
    kiosk.open_admin_tab(vm.ADMIN)
    assert kiosk.view(T0).screen == vm.PIN            # locked -> asks for the PIN

    assert kiosk.unlock(operator_id, "000000", T0) is False
    view = kiosk.view(T0)
    assert view.screen == vm.PIN and "Còn 4 lần" in view.message

    assert kiosk.unlock(operator_id, "123456", T0) is True
    assert kiosk.view(T0).screen == vm.ADMIN
    # the operator id rides along with every command from now on
    kiosk.send("retry", now=T0)
    assert kiosk_ipc.claim_commands(conn, at=T0 + 1)[0]["payload"]["operator_id"] == operator_id


def test_admin_locks_itself_when_untouched(kiosk, conn):
    with db.transaction(conn):
        operator_id = operators.create(conn, "Nurse A", "123456", iterations=FAST, at=T0)
    kiosk.poll(T0)
    kiosk.open_admin_tab(vm.ADMIN)
    kiosk.unlock(operator_id, "123456", T0)
    assert kiosk.view(T0 + 30).screen == vm.ADMIN      # still within admin_lock_s (60 s)
    assert kiosk.view(T0 + 200).screen == vm.PIN       # C-21: locked after 60 s idle


def test_logout_locks_immediately(kiosk, conn):
    with db.transaction(conn):
        operator_id = operators.create(conn, "Nurse A", "123456", iterations=FAST, at=T0)
    kiosk.poll(T0)
    kiosk.open_admin_tab(vm.ADMIN)
    kiosk.unlock(operator_id, "123456", T0)
    kiosk.logout()
    assert kiosk.auth.is_unlocked(T0) is False and kiosk.local_screen is None


def test_status_rows_read_the_shared_database(kiosk, conn):
    add_patient(conn, "BN001", "A")
    kiosk.poll(T0)
    rows = dict(kiosk.status_rows(T0))
    assert rows["Bệnh nhân đang hoạt động"] == "1"
    assert rows["Sự kiện chờ gửi"] == "0"
    assert rows["Lần đồng bộ gần nhất"] == "chưa có"
    assert rows["Trạng thái engine"] == "IDLE"


def test_status_reports_a_silent_engine(kiosk, conn):
    kiosk.poll(T0)
    assert dict(kiosk.status_rows(T0 + 60))["Trạng thái engine"] == "?"


def test_preview_is_optional(kiosk, cfg):
    assert kiosk.preview_bytes() is None               # engine has not written one yet
    with open(cfg["kiosk"]["preview_path"], "wb") as f:
        f.write(b"jpegdata")
    assert kiosk.preview_bytes() == b"jpegdata"


def test_enroll_command_carries_the_form(kiosk, conn):
    with db.transaction(conn):
        operator_id = operators.create(conn, "Nurse A", "123456", iterations=FAST, at=T0)
    kiosk.poll(T0)
    kiosk.open_admin_tab(vm.ADMIN)
    kiosk.unlock(operator_id, "123456", T0)
    kiosk.start_enroll({"patient_code": "BN007", "full_name": "Lê Văn C"}, T0)
    command = kiosk_ipc.claim_commands(conn, at=T0 + 1)[0]
    assert command["type"] == "start_enroll"
    assert command["payload"]["patient_code"] == "BN007"
    assert command["payload"]["operator_id"] == operator_id


# --------------------------------------------------------------------- admin menu


def unlocked(kiosk, conn, at=T0):
    with db.transaction(conn):
        operator_id = operators.create(conn, "Nurse A", "123456", iterations=FAST, at=at)
    kiosk.poll(at)
    kiosk.open_admin_tab(vm.ADMIN)
    kiosk.unlock(operator_id, "123456", at)
    return operator_id


def test_admin_menu_offers_every_function(kiosk, conn):
    """The admin screen used to hold one button ("log out") and nothing else."""
    unlocked(kiosk, conn)
    kinds = [button.kind for button in kiosk.view(T0).buttons]
    assert kinds == ["enroll", "patients", "status", "change_pin", "settings", "cancel"]


def test_redrawing_does_not_postpone_the_lock(kiosk, conn):
    """C-21: the window redraws ten times a second, and that must not count as activity.

    The lock used to be reset from view() itself, so the admin screen never locked while
    it was on display — which is precisely when it matters.
    """
    unlocked(kiosk, conn)
    for tick in range(1, 200):                       # 200 redraws, no taps
        view = kiosk.view(T0 + tick)
    assert view.screen == vm.PIN


def test_a_tap_postpones_the_lock(kiosk, conn):
    unlocked(kiosk, conn)
    for tick in range(1, 200):
        kiosk.view(T0 + tick)
        if tick % 30 == 0:                           # the nurse is actually using it
            kiosk.touch(T0 + tick)
    assert kiosk.view(T0 + 200).screen == vm.ADMIN


def test_taking_the_enrolment_shots_does_not_lock_the_screen(kiosk, conn):
    """Nobody touches the screen while the patient is being photographed."""
    unlocked(kiosk, conn)
    for tick in range(1, 200):
        # The engine keeps publishing while it collects; a silent engine would rightly
        # put the "engine down" screen up instead, which is a different test.
        publish(conn, "ENROLL_COLLECTING", at=T0 + tick)
        kiosk.poll(T0 + tick)
        view = kiosk.view(T0 + tick)
    # The engine owns the screen during the shots, so the nurse sees the shot counter,
    # not the admin menu - but the admin session behind it must still be unlocked.
    assert view.screen == vm.ENROLL
    assert kiosk.auth.is_unlocked(T0 + 200) is True
    assert kiosk.local_screen == vm.ADMIN


def test_the_admin_menu_returns_after_the_enrolment_finishes(kiosk, conn):
    unlocked(kiosk, conn)
    publish(conn, "ENROLL_COLLECTING", at=T0 + 1)
    kiosk.poll(T0 + 1)
    assert kiosk.view(T0 + 2).screen == vm.ENROLL
    publish(conn, "COOLDOWN", at=T0 + 3)
    kiosk.poll(T0 + 3)
    assert kiosk.view(T0 + 4).screen == vm.ADMIN      # ready for the next patient


def test_back_returns_to_the_menu_instead_of_logging_out(kiosk, conn):
    unlocked(kiosk, conn)
    kiosk.open_admin_tab(vm.STATUS)
    back = [b for b in kiosk.view(T0).buttons if b.kind == "cancel"][0]
    kiosk.on_button(back, T0)
    assert kiosk.local_screen == vm.ADMIN
    assert kiosk.auth.is_unlocked(T0) is True


# --------------------------------------------------------------------- revocation


def test_revoking_removes_the_patient_and_bumps_the_gallery(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    unlocked(kiosk, conn)
    before = templates.gallery_version(conn)

    kiosk.open_admin_tab(vm.PATIENTS)
    kiosk.select_patient("BN001")
    revoke = [b for b in kiosk.view(T0).buttons if b.kind == "revoke"][0]
    kiosk.on_button(revoke, T0)

    assert patients.get(conn, "BN001") is None
    # The engine only reloads when the version changes, so this is what makes it stick.
    assert templates.gallery_version(conn) > before
    assert "BN001" in kiosk.view(T0).message


def test_revoke_button_appears_only_with_a_patient_selected(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    unlocked(kiosk, conn)
    kiosk.open_admin_tab(vm.PATIENTS)
    assert [b.kind for b in kiosk.view(T0).buttons] == ["cancel"]
    kiosk.select_patient("BN001")
    assert "revoke" in [b.kind for b in kiosk.view(T0).buttons]


def test_empty_patient_list_says_so(kiosk, conn):
    unlocked(kiosk, conn)
    kiosk.open_admin_tab(vm.PATIENTS)
    view = kiosk.view(T0)
    assert view.fields == () and "Chưa có bệnh nhân" in view.message


# --------------------------------------------------------------------- candidate face


def test_candidate_face_is_the_enrolment_crop_of_the_candidate(kiosk, conn):
    from edgeface.storage import faces

    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    add_patient(conn, "BN002", "Trần Văn B")
    with db.transaction(conn):
        faces.save(conn, "BN001", b"jpeg-of-BN001", T0)
    assert kiosk.candidate_face() is None                       # no state yet

    publish(conn, "AWAIT_NURSE", payload={
        "decision": "review_required", "candidate": {"code": "BN001", "score": 0.8}})
    kiosk.poll(T0)
    assert kiosk.candidate_face() == b"jpeg-of-BN001"

    publish(conn, "AWAIT_NURSE", payload={
        "decision": "review_required", "candidate": {"code": "BN002", "score": 0.8}})
    kiosk.poll(T0)
    assert kiosk.candidate_face() is None                       # BN002 has no picture

    publish(conn, "AWAIT_NURSE", payload={"decision": "no_match"})
    kiosk.poll(T0)
    assert kiosk.candidate_face() is None                       # nobody to show


# --------------------------------------------------------------------- first-run PIN


def test_a_kiosk_with_no_operator_creates_one_from_the_pin_screen(kiosk, conn):
    kiosk.poll(T0)
    kiosk.open_admin_tab(vm.ADMIN)
    view = kiosk.view(T0)
    assert view.screen == vm.PIN and "Tạo mã PIN" in view.title
    assert kiosk.needs_setup() is True

    assert kiosk.submit_pin("123456", T0) is False
    assert "Nhập lại" in kiosk.view(T0).message               # the second step
    assert operators.count(conn) == 0                          # nothing saved yet

    assert kiosk.submit_pin("123456", T0) is True
    view = kiosk.view(T0)
    assert view.screen == vm.ADMIN and "Đã tạo mã PIN" in view.message
    assert operators.count(conn) == 1
    assert kiosk.needs_setup() is False

    # The new PIN is the one that unlocks from now on, and the screen no longer offers setup.
    kiosk.logout()
    kiosk.open_pin()
    assert kiosk.view(T0).title != "Tạo mã PIN quản trị"
    assert kiosk.submit_pin("000000", T0) is False
    assert kiosk.submit_pin("123456", T0) is True


def test_setup_rejects_a_mistyped_repeat_and_saves_nothing(kiosk, conn):
    kiosk.open_pin()
    kiosk.submit_pin("123456", T0)
    assert kiosk.submit_pin("123457", T0) is False
    view = kiosk.view(T0)
    assert "không giống nhau" in view.message and view.severity == vm.ATTENTION
    assert operators.count(conn) == 0
    assert kiosk.local_context["step"] == "new"                # asked from the start again


def test_setup_rejects_a_pin_of_the_wrong_length(kiosk, conn):
    kiosk.open_pin()
    assert kiosk.submit_pin("123", T0) is False
    assert "6 chữ số" in kiosk.view(T0).message
    assert kiosk.local_context["step"] == "new"
    assert operators.count(conn) == 0


def test_setup_does_not_create_a_second_operator(kiosk, conn):
    """db_admin.py may create the operator while the nurse is on the second step."""
    kiosk.open_pin()
    kiosk.submit_pin("123456", T0)
    with db.transaction(conn):
        operators.create(conn, "Nurse A", "999999", iterations=FAST, at=T0)
    assert kiosk.submit_pin("123456", T0) is False
    assert operators.count(conn) == 1
    assert kiosk.view(T0).title != "Tạo mã PIN quản trị"      # back to the ordinary PIN screen


# --------------------------------------------------------------------- change PIN


def test_change_pin_walks_old_new_repeat(kiosk, conn):
    operator_id = unlocked(kiosk, conn)
    kiosk.open_change_pin()
    assert kiosk.submit_change_pin("123456", T0) == "new"
    assert kiosk.submit_change_pin("654321", T0) == "repeat"
    assert kiosk.submit_change_pin("654321", T0) == "done"
    assert kiosk.local_screen == vm.ADMIN

    kiosk.logout()
    assert kiosk.unlock(operator_id, "123456", T0) is False      # the old PIN is gone
    assert kiosk.unlock(operator_id, "654321", T0) is True


def test_change_pin_rejects_a_mistyped_repeat(kiosk, conn):
    """A typo here would lock the nurse out of the kiosk, with no way back in from it."""
    operator_id = unlocked(kiosk, conn)
    kiosk.open_change_pin()
    kiosk.submit_change_pin("123456", T0)
    kiosk.submit_change_pin("654321", T0)
    assert kiosk.submit_change_pin("654322", T0) == "new"         # back a step, not saved
    assert "không giống nhau" in kiosk.view(T0).message
    kiosk.logout()
    assert kiosk.unlock(operator_id, "123456", T0) is True        # PIN never changed


def test_change_pin_rejects_a_wrong_current_pin(kiosk, conn):
    operator_id = unlocked(kiosk, conn)
    kiosk.open_change_pin()
    kiosk.submit_change_pin("999999", T0)
    kiosk.submit_change_pin("654321", T0)
    assert kiosk.submit_change_pin("654321", T0) == "old"
    assert "hiện tại không đúng" in kiosk.view(T0).message
    kiosk.logout()
    assert kiosk.unlock(operator_id, "123456", T0) is True


# --------------------------------------------------------------------- preview


def test_an_unchanged_preview_is_not_read_again(kiosk, cfg):
    """Decoding and repainting a picture already on screen is pure waste, and at fifteen
    frames a second there is no room for it."""
    path = cfg["kiosk"]["preview_path"]
    assert kiosk.preview_changed() is False          # nothing written yet

    with open(path, "wb") as f:
        f.write(b"first")
    assert kiosk.preview_changed() is True
    assert kiosk.preview_changed() is False          # same file, same answer


def test_a_new_preview_frame_is_noticed(kiosk, cfg):
    path = cfg["kiosk"]["preview_path"]
    with open(path, "wb") as f:
        f.write(b"first")
    kiosk.preview_changed()
    with open(path, "wb") as f:
        f.write(b"second frame, different size")     # the engine renames a new file in
    assert kiosk.preview_changed() is True


def test_a_missing_preview_is_not_an_error(kiosk):
    """Normal while the engine starts up, or if /dev/shm was cleared."""
    assert kiosk.preview_changed() is False
    assert kiosk.preview_bytes() is None


# ---------------------------------------------------------------- the redesign
def unlock_admin(kiosk, conn, pin="123456"):
    with db.transaction(conn):
        operator = operators.create(conn, "Nurse A", pin, iterations=FAST, at=T0)
    kiosk.unlock(operator, pin, T0)
    return operator


def test_patient_rows_say_where_a_record_came_from(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    with db.transaction(conn):
        patients.upsert_patient(conn, "BN002", "Trần Văn Bình", 1988, "server", T0)
    rows = kiosk.patient_rows(T0)
    assert "đăng ký tại kiosk" in rows["BN001"]["sub"]
    assert "tải từ server" in rows["BN002"]["sub"]
    assert rows["BN001"]["trash"] is True
    assert rows["BN001"]["trailing"].startswith("hết hạn")


def test_patient_rows_count_templates_in_one_query(kiosk, conn):
    import numpy as np

    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    with db.transaction(conn):
        templates.add_templates(conn, "BN001",
                                [np.zeros(512, dtype="float32") for _ in range(3)],
                                "sha", created_at=T0)
    assert "3 đặc trưng" in kiosk.patient_rows(T0)["BN001"]["sub"]


def test_status_tiles_say_whether_the_number_is_good_news(kiosk, conn):
    add_patient(conn, "BN001", "A")
    kiosk.poll(T0)
    tiles = dict((label, (value, foot, tone))
                 for label, value, foot, tone in kiosk.status_tiles(T0))
    assert tiles["Sự kiện chờ gửi"][0] == "0"
    assert tiles["Sự kiện chờ gửi"][1] == "không còn gì chờ gửi"
    assert tiles["Sự kiện chờ gửi"][2] == vm.OK
    assert tiles["Trạng thái engine"][0] == "IDLE"


def test_a_silent_engine_turns_its_tile_red(kiosk, conn):
    kiosk.poll(T0)
    tiles = dict((label, tone) for label, _v, _f, tone in kiosk.status_tiles(T0 + 60))
    assert tiles["Trạng thái engine"] == vm.ALARM


def test_the_board_numbers_reach_the_status_screen(kiosk, conn):
    publish(conn, "IDLE", payload={"device": {"ram_mb": 2100, "ram_total_mb": 3956,
                                              "temp_c": 48, "cpu_pct": 37},
                                   "telemetry": {"fps": 12.4}})
    kiosk.poll(T0)
    tiles = dict((label, value) for label, value, _f, _t in kiosk.status_tiles(T0))
    assert tiles["Tốc độ khung"] == "12.4"
    assert tiles["RAM đang dùng"] == "2100"
    assert tiles["Nhiệt độ"] == "48°C"
    assert "RAM 2100 / 3956 MB" in kiosk.device_line()


def test_the_status_screen_works_without_a_board_to_read(kiosk, conn):
    """A dev machine has no tegrastats, and the screen must not invent numbers."""
    kiosk.poll(T0)
    labels = [label for label, _v, _f, _t in kiosk.status_tiles(T0)]
    assert "RAM đang dùng" not in labels and "Nhiệt độ" not in labels


def test_asking_for_a_sync_leaves_a_note_the_sync_process_reads(kiosk, conn):
    from edgeface.storage.db import get_meta

    unlock_admin(kiosk, conn)
    kiosk.open_admin_tab(vm.STATUS)
    kiosk.on_button(vm.Button("sync", "Đồng bộ ngay", None), T0)
    assert float(get_meta(conn, "sync_requested_at")) == T0
    assert "Đã yêu cầu đồng bộ" in kiosk.view(T0).message


def test_the_admin_cards_carry_their_own_numbers(kiosk, conn):
    add_patient(conn, "BN001", "Nguyễn Thị Hà")
    unlock_admin(kiosk, conn)
    kiosk.poll(T0)
    summary = kiosk.admin_summary(T0)
    assert "1 đang hoạt động" in summary["patients"]
    assert "1 đăng ký tại kiosk" in summary["patients"]
    assert "0 sự kiện chờ gửi" in summary["status"]
    assert summary["change_pin"] == "chưa đổi lần nào"


def test_the_pin_card_says_how_old_the_pin_is(kiosk, conn):
    unlock_admin(kiosk, conn)
    kiosk.submit_change_pin("123456", T0)
    kiosk.submit_change_pin("654321", T0)
    kiosk.submit_change_pin("654321", T0)
    assert kiosk.admin_summary(T0 + 14 * 86400)["change_pin"] == "đổi lần cuối 14 ngày trước"


def test_the_rail_way_out_logs_out_from_wherever_it_is_tapped(kiosk, conn):
    """"cancel" is the back button; from the patient list it means up to the menu."""
    unlock_admin(kiosk, conn)
    kiosk.open_admin_tab(vm.PATIENTS)
    kiosk.on_button(vm.Button("cancel", "Quay lại menu", None), T0)
    assert kiosk.local_screen == vm.ADMIN and kiosk.auth.is_unlocked(T0)

    kiosk.open_admin_tab(vm.PATIENTS)
    kiosk.on_button(vm.Button("logout", "Thoát", None), T0)
    assert kiosk.auth.is_unlocked(T0) is False and kiosk.local_screen is None


# ---------------------------------------------------------------- match settings tab
def test_settings_tab_steps_inside_the_configured_range(kiosk, conn):
    unlocked(kiosk, conn)
    kiosk.on_button(vm.Button("settings", "", None), T0)
    view = kiosk.view(T0)
    assert view.screen == vm.SETTINGS
    rows = dict((row["key"], row) for row in kiosk.settings_rows())
    assert rows["match.threshold"]["value"] == "0.80"
    assert rows["match.margin_top1_top2"]["value"] == u"Không xét"

    assert kiosk.adjust_setting("match.threshold", +1, T0) == 0.85
    for _ in range(10):
        kiosk.adjust_setting("match.threshold", +1, T0)
    assert kiosk.local_context["draft"]["match.threshold"] == 0.95          # capped
    assert kiosk.settings_rows()[1]["can_inc"] is False or \
        dict((r["key"], r) for r in kiosk.settings_rows())["match.threshold"]["can_inc"] is False
    for _ in range(20):
        kiosk.adjust_setting("match.threshold", -1, T0)
    assert kiosk.local_context["draft"]["match.threshold"] == 0.50          # floor, not empty

    # The margin may be empty: one step up starts at its minimum, one down empties it.
    assert kiosk.adjust_setting("match.margin_top1_top2", +1, T0) == 0.05
    assert kiosk.adjust_setting("match.margin_top1_top2", -1, T0) is None


def test_saving_writes_only_what_changed_as_the_unlocked_nurse(kiosk, conn):
    from edgeface.storage import settings

    operator_id = unlocked(kiosk, conn)
    kiosk.open_settings()
    assert kiosk.save_settings(T0) is False                   # nothing changed yet
    assert kiosk.view(T0).message == u"Không có thay đổi nào để lưu."

    kiosk.adjust_setting("match.threshold", +1, T0)
    assert kiosk.save_settings(T0) is True
    assert settings.overrides(conn, kiosk.cfg) == {"match.threshold": 0.85}
    info = settings.describe(conn, kiosk.cfg, "match.threshold")
    assert info["operator_id"] == operator_id
    assert "Nurse A" in dict((r["key"], r) for r in kiosk.settings_rows())[
        "match.threshold"]["source"]

    kiosk.on_button(vm.Button("settings_reset", "", None), T0)
    assert settings.overrides(conn, kiosk.cfg) == {}


def test_settings_tab_needs_the_pin_and_back_leads_to_the_menu(kiosk, conn):
    kiosk.open_admin_tab(vm.SETTINGS)
    assert kiosk.view(T0).screen == vm.PIN                     # locked: PIN first
    unlocked(kiosk, conn)
    kiosk.open_settings()
    kiosk.on_button(vm.Button("cancel", "", None), T0)
    assert kiosk.view(T0).screen == vm.ADMIN


def test_settings_screen_quotes_recent_confirmed_scores(kiosk, conn):
    from edgeface.storage import sessions

    with db.transaction(conn):
        for i, (score, action, confirmed) in enumerate(((0.86, "confirm", "BN001"),
                                                        (0.90, "confirm", "BN001"),
                                                        (0.40, "reject", None))):
            sid = sessions.open_session(conn, "identify", T0 + i)
            sessions.close_session(conn, sid, ended_at=T0 + i, top1_code="BN001",
                                   top1_score=score, nurse_action=action,
                                   confirmed_code=confirmed)
    unlocked(kiosk, conn)
    kiosk.open_settings()
    assert sorted(kiosk.recent_confirmed_scores()) == [0.86, 0.90]
    assert "0.86 – 0.90" in kiosk.view(T0).message
