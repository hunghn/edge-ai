"""The session state machine, tested without a database, camera or models."""
import os

import pytest

from edgeface import config as cfg_mod
from edgeface.engine import session as sm
from edgeface.engine.loop import FrameOutcome
from edgeface.pipeline import best_frame as bf
from edgeface.pipeline.decision import DecisionResult
from edgeface.types import Decision, FaceObs, GuidanceCode, SpoofScore

T0 = 1000.0


@pytest.fixture
def cfg(repo_root):
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


def outcome(guidance=None, collector=bf.COLLECTING, p_real=None, frame_id=1):
    spoof = None if p_real is None else SpoofScore(p_real, None, 0, {})
    obs = FaceObs(frame_id=frame_id, ts=T0, det="det", spoof=spoof)
    return FrameOutcome(guidance, None, obs, collector, None)


def kinds(actions):
    return [a.kind for a in actions]


def payload_of(actions, kind):
    return next(a.payload for a in actions if a.kind == kind)


def decision(value=Decision.REVIEW_REQUIRED, candidate=None, rule="R3"):
    return DecisionResult(value, rule, candidate, True, None)


def drive_to_await(session, now=T0):
    session.on_frame(outcome(GuidanceCode.STEP_CLOSER), now)
    session.session_id = "sess-1"
    session.on_frame(outcome(collector=bf.READY), now)
    session.on_decision(decision(candidate={"code": "BN001", "score": 0.8, "margin": 0.2,
                                            "votes": 5, "k": 5}), now)
    return session


# ---------------------------------------------------------------- identify flow
def test_idle_stays_idle_without_a_face(cfg):
    session = sm.Session(cfg)
    assert session.on_frame(outcome(GuidanceCode.NO_FACE), T0) == []
    assert session.state == sm.IDLE


def test_a_face_opens_a_session(cfg):
    session = sm.Session(cfg)
    actions = session.on_frame(outcome(GuidanceCode.STEP_CLOSER), T0)
    assert session.state == sm.GUIDING
    assert kinds(actions) == [sm.OPEN_SESSION, sm.PUBLISH]
    assert payload_of(actions, sm.PUBLISH)["guidance"] == GuidanceCode.STEP_CLOSER


def test_good_frames_move_to_collecting_then_decide(cfg):
    session = sm.Session(cfg)
    session.on_frame(outcome(GuidanceCode.STEP_CLOSER), T0)
    session.on_frame(outcome(), T0 + 0.1)
    assert session.state == sm.COLLECTING
    actions = session.on_frame(outcome(collector=bf.READY), T0 + 0.2)
    assert session.state == sm.DECIDED and kinds(actions) == [sm.DECIDE]
    assert payload_of(actions, sm.DECIDE)["collector"] == bf.READY


def test_low_quality_also_reaches_a_decision(cfg):
    session = sm.Session(cfg)
    session.on_frame(outcome(GuidanceCode.STEP_CLOSER), T0)
    actions = session.on_frame(outcome(GuidanceCode.HOLD_STILL, collector=bf.LOW_QUALITY),
                               T0 + 1.6)
    assert payload_of(actions, sm.DECIDE)["collector"] == bf.LOW_QUALITY


def test_losing_the_face_cancels_the_session(cfg):
    session = sm.Session(cfg)
    session.on_frame(outcome(GuidanceCode.STEP_CLOSER), T0)
    session.session_id = "sess-1"
    # A short gap only updates the kiosk ("step into the frame"), it does not end anything
    brief = session.on_frame(outcome(GuidanceCode.NO_FACE), T0 + 0.5)
    assert kinds(brief) == [sm.PUBLISH] and session.state == sm.GUIDING
    actions = session.on_frame(outcome(GuidanceCode.NO_FACE), T0 + 5.0)
    assert payload_of(actions, sm.CLOSE_SESSION)["nurse_action"] == "cancel"
    assert session.state == sm.IDLE


def test_the_runner_owns_the_session_id(cfg):
    """A regression: the machine used to clear session_id before CLOSE_SESSION ran,
    which silently left every session row open and empty."""
    session = drive_to_await(sm.Session(cfg))
    actions = session.on_command({"type": "confirm", "payload": {}}, T0 + 1)
    assert sm.CLOSE_SESSION in kinds(actions)
    assert session.session_id == "sess-1"      # still set for the runner to use


def test_confirm_uses_the_candidate_when_no_code_is_given(cfg):
    session = drive_to_await(sm.Session(cfg))
    actions = session.on_command({"type": "confirm", "payload": {}}, T0 + 1)
    assert payload_of(actions, sm.CLOSE_SESSION)["confirmed_code"] == "BN001"
    assert session.state == sm.COOLDOWN


def test_manual_selection_overrides_the_candidate(cfg):
    session = drive_to_await(sm.Session(cfg))
    actions = session.on_command({"type": "manual", "payload": {"code": "BN999"}}, T0 + 1)
    closed = payload_of(actions, sm.CLOSE_SESSION)
    assert closed["nurse_action"] == "manual" and closed["confirmed_code"] == "BN999"


def test_spoof_decision_asks_for_evidence(cfg):
    session = sm.Session(cfg)
    session.session_id = "sess-1"
    actions = session.on_decision(decision(Decision.SPOOF_SUSPECT, rule="R1"), T0)
    assert sm.SAVE_EVIDENCE in kinds(actions)
    assert payload_of(actions, sm.PUBLISH)["decision"] == "spoof_suspect"


def test_frames_are_ignored_while_waiting_for_the_nurse(cfg):
    session = drive_to_await(sm.Session(cfg))
    good_before = session.n_good_frames
    assert session.on_frame(outcome(), T0 + 1) == []
    assert session.state == sm.AWAIT_NURSE
    assert session.n_good_frames == good_before   # frames now belong to no session


def test_nurse_timeout_then_cooldown_then_idle(cfg):
    session = drive_to_await(sm.Session(cfg))
    assert session.on_tick(T0 + 29) == []                       # C-21: 30 s
    actions = session.on_tick(T0 + 31)
    assert payload_of(actions, sm.CLOSE_SESSION)["nurse_action"] == "timeout"
    assert session.state == sm.COOLDOWN
    assert session.on_tick(T0 + 32) == []                       # C-21: 3 s cooldown
    assert kinds(session.on_tick(T0 + 35)) == [sm.PUBLISH]
    assert session.state == sm.IDLE


def test_stale_commands_are_ignored(cfg):
    session = sm.Session(cfg)
    assert session.on_command({"type": "confirm", "payload": {}}, T0) == []
    assert session.state == sm.IDLE


def test_spoof_frames_and_min_p_real_are_counted(cfg):
    session = sm.Session(cfg)
    session.on_frame(outcome(GuidanceCode.SPOOF_SUSPECT, p_real=0.4), T0)
    session.on_frame(outcome(GuidanceCode.SPOOF_SUSPECT, p_real=0.2), T0 + 0.1)
    session.on_frame(outcome(), T0 + 0.2)
    assert session.spoof_frames == 2
    assert session.min_p_real == pytest.approx(0.2)
    assert session.n_good_frames == 1


# ---------------------------------------------------------------- enrollment flow
def test_enrollment_branch(cfg):
    session = sm.Session(cfg)
    form = {"patient_code": "BN001", "full_name": "A"}
    actions = session.on_command({"type": "start_enroll", "payload": form}, T0)
    assert kinds(actions) == [sm.RESET_COLLECTOR, sm.START_ENROLL, sm.PUBLISH]
    assert session.state == sm.ENROLL_GUIDING and session.is_enrolling()

    session.session_id = "sess-enroll"
    actions = session.on_frame(outcome(), T0 + 0.1)
    assert session.state == sm.ENROLL_COLLECTING
    assert payload_of(actions, sm.PUBLISH)["progress"] == 1

    actions = session.on_frame(outcome(collector=bf.READY), T0 + 0.5)
    assert session.state == sm.ENROLL_REVIEW
    assert payload_of(actions, sm.SAVE_ENROLL)["stage"] == "review"

    actions = session.on_command({"type": "enroll_confirm", "payload": {}}, T0 + 1)
    assert payload_of(actions, sm.SAVE_ENROLL)["stage"] == "commit"
    assert session.state == sm.COOLDOWN


def test_enrollment_can_be_cancelled(cfg):
    session = sm.Session(cfg)
    session.on_command({"type": "start_enroll", "payload": {"patient_code": "BN1",
                                                            "full_name": "A"}}, T0)
    session.session_id = "sess-enroll"
    actions = session.on_command({"type": "enroll_cancel", "payload": {}}, T0 + 1)
    assert sm.CANCEL_ENROLL in kinds(actions) and session.state == sm.COOLDOWN
    assert session.enroll_form is None


def test_enrollment_times_out(cfg):
    session = sm.Session(cfg)
    session.on_command({"type": "start_enroll", "payload": {"patient_code": "BN1",
                                                            "full_name": "A"}}, T0)
    actions = session.on_frame(outcome(GuidanceCode.HOLD_STILL), T0 + 31)   # enroll.timeout_s
    assert session.state == sm.ENROLL_ERROR
    assert payload_of(actions, sm.PUBLISH)["reason"] == "timeout"


# ---------------------------------------------------------------- camera
def test_camera_error_closes_the_session_and_recovers(cfg):
    session = sm.Session(cfg)
    session.on_frame(outcome(GuidanceCode.STEP_CLOSER), T0)
    session.session_id = "sess-1"
    actions = session.on_camera_error(T0 + 1)
    assert sm.CLOSE_SESSION in kinds(actions) and session.state == sm.CAMERA_ERROR
    assert session.on_camera_error(T0 + 2) == []          # no repeated alarms
    actions = session.on_camera_ok(T0 + 3)
    assert session.state == sm.IDLE and kinds(actions) == [sm.PUBLISH]
