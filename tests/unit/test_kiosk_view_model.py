# -*- coding: utf-8 -*-
"""What the kiosk shows for each engine state."""
import pytest

from edgeface.kiosk import strings, view_model as vm

T0 = 1000.0


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
