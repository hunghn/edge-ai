# -*- coding: utf-8 -*-
"""What the kiosk shows for each engine state."""
import os

import pytest

from edgeface import config as cfg_mod
from edgeface.kiosk import strings, view_model as vm

T0 = 1000.0


@pytest.fixture
def cfg(repo_root):
    """The real thresholds, so a metric row is checked against the shipped limits."""
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


def state(engine_state, guidance=None, payload=None, seq=1, session_id="s1"):
    return {"seq": seq, "state": engine_state, "guidance_code": guidance,
            "session_id": session_id, "payload": payload, "updated_at": T0}


def candidate_payload(decision="review_required", code="BN001"):
    return {"decision": decision, "rule_id": "R3",
            "candidate": {"code": code, "score": 0.81, "margin": 0.2, "votes": 5, "k": 5}}


def test_idle():
    view = vm.build(state("IDLE"), T0)
    assert view.screen == vm.IDLE and view.message == strings.IDLE_HINT
    assert view.show_preview is False


@pytest.mark.parametrize("code,expected", [
    ("STEP_CLOSER", "Vui lòng đứng gần hơn"),
    ("MOVE_TO_CENTER", "Vui lòng đứng vào giữa khung"),
    ("LOOK_STRAIGHT", "Vui lòng nhìn thẳng vào camera"),
    ("TOO_DARK", "Chỗ đứng quá tối, vui lòng nhích lên phía trước"),
])
def test_every_guidance_code_has_an_instruction(code, expected):
    view = vm.build(state("GUIDING", code), T0)
    assert view.screen == vm.GUIDANCE and view.message == expected
    assert view.show_preview is True


def test_unknown_guidance_code_still_says_something_useful():
    assert strings.guidance("SOMETHING_NEW") == strings.GUIDANCE_DEFAULT


def test_candidate_card_shows_the_patient_and_four_buttons():
    patient = {"full_name": "Nguyễn Thị Hà", "birth_year": 1990, "appointment_code": "AP1"}
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, patient)
    assert view.screen == vm.CANDIDATE
    labels = dict(view.fields)
    assert labels[strings.LABEL_CODE] == "BN001"
    assert labels[strings.LABEL_NAME] == "Nguyễn Thị Hà"
    assert labels[strings.LABEL_APPOINTMENT] == "AP1"
    assert [b.kind for b in view.buttons] == ["confirm", "reject", "retry", "search"]


def test_the_card_shows_the_score_and_the_gap_to_the_runner_up():
    """Both numbers, and the word as well: the word is what is read at a glance."""
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, {})
    rows = dict(view.fields)
    assert rows[strings.LABEL_SCORE] == "0.81"
    assert rows[strings.LABEL_MARGIN] == "0.20"
    assert rows[strings.LABEL_CONFIDENCE] == strings.CONFIDENCE_LOW


def test_the_score_is_never_a_percentage():
    """It is a cosine similarity. A % sign would claim an accuracy nothing has measured,
    and the conversion to a probability needs the calibration of D-01, which has no data."""
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, {})
    rendered = " ".join([view.title, view.message] + [str(v) for _, v in view.fields])
    assert "%" not in rendered
    assert "81%" not in rendered


def test_the_score_can_be_switched_off_for_the_clinic():
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, {},
                    show_score=False)
    rows = dict(view.fields)
    assert strings.LABEL_SCORE not in rows and strings.LABEL_MARGIN not in rows
    assert rows[strings.LABEL_CONFIDENCE] == strings.CONFIDENCE_LOW


def test_a_candidate_without_a_margin_still_renders():
    """no_match and some rule paths publish a score with nothing to compare it against."""
    payload = candidate_payload()
    payload["candidate"].pop("margin")
    rows = dict(vm.build(state("AWAIT_NURSE", payload=payload), T0, {}).fields)
    assert rows[strings.LABEL_SCORE] == "0.81"
    assert strings.LABEL_MARGIN not in rows


def test_the_candidate_card_shows_the_camera(kiosk_preview=None):
    """The nurse compares a face to a name, so the face has to be on the screen."""
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, {})
    assert view.show_preview is True


def test_high_confidence_label_when_the_decision_is_confident():
    view = vm.build(state("AWAIT_NURSE",
                          payload=candidate_payload("candidate_suggested")), T0, {})
    assert dict(view.fields)[strings.LABEL_CONFIDENCE] == strings.CONFIDENCE_HIGH
    assert view.severity == vm.OK


def test_spoof_alert_hides_patient_details():
    payload = candidate_payload("spoof_suspect")
    view = vm.build(state("AWAIT_NURSE", payload=payload), T0,
                    {"full_name": "Nguyễn Thị Hà"})
    assert view.screen == vm.ALERT and view.severity == vm.ALARM
    assert "Nguyễn Thị Hà" not in view.message
    assert view.fields == ()
    assert [b.kind for b in view.buttons] == ["retry", "search"]


def test_low_quality_and_no_match_offer_retry():
    for decision in ("low_quality", "no_match"):
        view = vm.build(state("AWAIT_NURSE", payload={"decision": decision}), T0)
        assert view.screen == vm.ALERT and view.severity == vm.ATTENTION
        assert [b.kind for b in view.buttons] == ["retry", "search"]


def test_countdown_is_passed_through():
    """The engine publishes an absolute deadline; the kiosk turns it into seconds left.

    The engine also heartbeats while waiting, so `last_update` stays fresh and the
    screen does not flip to "engine down" during the 30 s the nurse has (C-21).
    """
    payload = candidate_payload()
    payload["timeout_at"] = T0 + 30
    view = vm.build(state("AWAIT_NURSE", payload=payload), T0 + 10, {}, last_update=T0 + 10)
    assert view.countdown_s == pytest.approx(20.0)


def test_engine_silence_becomes_an_error_screen():
    view = vm.build(state("GUIDING", "STEP_CLOSER"), T0 + 60, last_update=T0)
    assert view.screen == vm.ERROR and view.message == strings.STATUS_ENGINE_DOWN
    assert vm.build(None, T0).screen == vm.ERROR


def test_camera_error():
    view = vm.build(state("CAMERA_ERROR"), T0)
    assert view.screen == vm.ERROR and view.message == strings.STATUS_CAMERA


def test_enrollment_progress_and_review():
    collecting = vm.build(state("ENROLL_COLLECTING", payload={"progress": 3, "total": 5}), T0)
    assert collecting.screen == vm.ENROLL and collecting.show_preview is True
    assert "3/5" in dict(collecting.fields)[""]

    review = vm.build(state("ENROLL_REVIEW", payload={
        "n_templates": 5, "warnings": ["duplicate_face"], "duplicate_code": "BN009"}), T0)
    assert "BN009" in review.message and review.severity == vm.ATTENTION
    assert [b.kind for b in review.buttons] == ["enroll_confirm", "enroll_cancel"]


def test_enrollment_error_message():
    view = vm.build(state("ENROLL_ERROR", payload={"reason": "timeout"}), T0)
    assert view.message == strings.ENROLL_ERRORS["timeout"]


def test_the_card_names_the_runner_up_without_naming_them():
    """Two patients who look alike is the failure this clinic has to catch, and it is
    invisible if only the winner reaches the screen. The code is masked all the same."""
    payload = candidate_payload()
    payload["candidate"]["top2_code"] = "BN000147"
    payload["candidate"]["top2_score"] = 0.79
    view = vm.build(state("AWAIT_NURSE", payload=payload), T0, {})
    rows = dict(view.fields)
    assert rows[strings.LABEL_LOOKALIKE] == "BN****47  0.79"
    assert "BN000147" not in " ".join(str(v) for v in rows.values())


def test_no_runner_up_row_when_the_gallery_holds_one_patient():
    """top2 is None with a single enrolled patient, which is the state of the kiosk now."""
    view = vm.build(state("AWAIT_NURSE", payload=candidate_payload()), T0, {})
    assert strings.LABEL_LOOKALIKE not in dict(view.fields)


def test_switching_the_score_off_hides_the_runner_up_too():
    payload = candidate_payload()
    payload["candidate"]["top2_code"] = "BN000147"
    payload["candidate"]["top2_score"] = 0.79
    view = vm.build(state("AWAIT_NURSE", payload=payload), T0, {}, show_score=False)
    assert strings.LABEL_LOOKALIKE not in dict(view.fields)


# ---------------------------------------------------------------- the redesign
def test_the_stepper_marks_the_gate_the_frame_stopped_at():
    """Standing in front of a silent screen is what the stepper is there to fix."""
    view = vm.build(state("GUIDING", guidance="STEP_CLOSER"), T0, last_update=T0)
    assert view.steps == (vm.DONE, vm.NOW, vm.TODO, vm.TODO, vm.TODO)
    view = vm.build(state("GUIDING", guidance="TOO_DARK"), T0, last_update=T0)
    assert view.steps == (vm.DONE, vm.DONE, vm.DONE, vm.NOW, vm.TODO)


def test_a_frame_that_passed_everything_is_waiting_on_the_match():
    view = vm.build(state("COLLECTING"), T0, last_update=T0)
    assert view.steps[-1] == vm.NOW and view.steps[0] == vm.DONE


def test_the_stepper_falls_back_to_the_stage_when_the_code_is_unknown():
    row = state("GUIDING", guidance="SOMETHING_NEW")
    row["payload"] = {"telemetry": {"stage": "S2"}}
    assert vm.build(row, T0, last_update=T0).steps[1] == vm.NOW


def test_the_shot_counter_appears_only_once_the_engine_counts():
    assert vm.build(state("COLLECTING"), T0, last_update=T0).progress is None
    row = state("COLLECTING")
    row["payload"] = {"telemetry": {"kept": 2, "need": 5}}
    assert vm.build(row, T0, last_update=T0).progress == (2, 5)


def test_a_quality_number_is_shown_against_the_threshold_it_missed(cfg):
    """"Độ nét 41" tells a nurse nothing; "41 < 60" tells them to steady the patient."""
    numbers = {"blur": 41, "lum": 52, "yaw": 4}
    rows = dict((label, value) for label, value, _tone in
                vm.quality_metrics(numbers, cfg))
    assert rows[strings.METRIC_BLUR] == "41 < 60"
    assert rows[strings.METRIC_LUM] == "52 < 60"
    assert rows[strings.METRIC_POSE].startswith("4")


def test_without_the_config_there_is_nothing_to_compare_against():
    assert vm.quality_metrics({"blur": 41}, None) == ()


def test_the_low_quality_screen_carries_the_numbers(cfg):
    row = state("AWAIT_NURSE", payload={"decision": "low_quality",
                                        "telemetry": {"blur": 41, "good": 2, "need": 5}})
    view = vm.build(row, T0, last_update=T0, cfg=cfg)
    assert view.screen == vm.ALERT
    assert any(label == strings.METRIC_BLUR for label, _v, _t in view.metrics)
    assert view.chips and "2/5" in view.chips[0][0]


def test_the_spoof_screen_shows_the_score_but_never_the_patient(cfg):
    row = state("AWAIT_NURSE", payload={"decision": "spoof_suspect",
                                        "candidate": {"code": "BN001", "score": 0.9},
                                        "telemetry": {"p_real": 0.41}})
    view = vm.build(row, T0, last_update=T0, cfg=cfg)
    assert view.fields == ()
    assert "0.41" in view.chips[0][0]
    assert "BN001" not in view.chips[0][0]


def test_the_diagnostic_chips_go_away_with_the_score(cfg):
    row = state("AWAIT_NURSE", payload={"decision": "spoof_suspect",
                                        "telemetry": {"p_real": 0.41}})
    assert vm.build(row, T0, last_update=T0, show_score=False, cfg=cfg).chips == ()


def test_the_camera_tags_are_diagnostics_too():
    assert vm.camera_tags({"fps": 12.4, "quality": 0.91}, show_score=False) == ()
    left, right = vm.camera_tags({"fps": 12.4})
    assert "12.4" in left and right == ""


def test_an_engine_that_sends_no_telemetry_still_renders():
    """The kiosk has to keep working against an engine that predates the payload."""
    view = vm.build(state("AWAIT_NURSE", payload={"decision": "low_quality"}), T0,
                    last_update=T0, cfg=None)
    assert view.screen == vm.ALERT
    assert view.metrics == () and view.chips == ()


def test_the_enrolment_view_numbers_its_steps():
    collecting = vm.build(state("ENROLL_COLLECTING", payload={"progress": 3, "total": 5}),
                          T0, last_update=T0)
    assert collecting.step == 1 and collecting.progress == (3, 5)
    review = vm.build(state("ENROLL_REVIEW", payload={"n_templates": 5,
                                                      "self_consistency": 0.94}),
                      T0, last_update=T0)
    assert review.step == 2
    assert dict((l, v) for l, v, _t in review.metrics)[strings.ENROLL_CONSISTENCY] == "0.94"
