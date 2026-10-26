"""Session state machine.

transition() is a pure function: (state, event) -> (new state, list of actions). It
touches no database, no camera and no models, which is what makes the whole engine
testable without hardware. engine/__main__.py executes the actions.

    IDLE -> GUIDING -> COLLECTING -> DECIDED -> AWAIT_NURSE -> COOLDOWN -> IDLE
                                                     |
                                     confirm/reject/manual/timeout

Enrollment runs the same pipeline on a separate branch:

    ENROLL_GUIDING -> ENROLL_COLLECTING -> ENROLL_REVIEW -> (confirm) -> COOLDOWN
"""
from collections import namedtuple

from edgeface.pipeline import best_frame as bf

# States, mirrored in storage.kiosk_ipc.STATES.
IDLE = "IDLE"
GUIDING = "GUIDING"
COLLECTING = "COLLECTING"
DECIDED = "DECIDED"
AWAIT_NURSE = "AWAIT_NURSE"
COOLDOWN = "COOLDOWN"
ENROLL_GUIDING = "ENROLL_GUIDING"
ENROLL_COLLECTING = "ENROLL_COLLECTING"
ENROLL_REVIEW = "ENROLL_REVIEW"
ENROLL_ERROR = "ENROLL_ERROR"
CAMERA_ERROR = "CAMERA_ERROR"

ENROLL_STATES = (ENROLL_GUIDING, ENROLL_COLLECTING, ENROLL_REVIEW, ENROLL_ERROR)

# Actions the runner performs. Names are deliberately verbs the engine can execute.
OPEN_SESSION = "open_session"
CLOSE_SESSION = "close_session"
PUBLISH = "publish"
DECIDE = "decide"
SAVE_EVIDENCE = "save_evidence"
RESET_COLLECTOR = "reset_collector"
START_ENROLL = "start_enroll"
SAVE_ENROLL = "save_enroll"
CANCEL_ENROLL = "cancel_enroll"

Action = namedtuple("Action", ["kind", "payload"])
Action.__new__.__defaults__ = (None,)


def telemetry(outcome, k_max=None):
    """The numbers behind the guidance line, for the kiosk to show beside it.

    Quantised on the way out. These values ride in the kiosk_state row, which the engine
    is careful to write only when something changed; a hundredth of a degree of yaw is
    not something changing, it is a camera being a camera.

    Only what the frame actually reached is included: a frame turned away at S2 has no
    blur to report, and an absent key is how the kiosk knows not to draw that row.
    """
    obs = getattr(outcome, "obs", None)
    out = {"stage": outcome.stage, "kept": outcome.kept}
    if k_max:
        out["need"] = int(k_max)
    if obs is None:
        return out
    # getattr rather than attribute access: this runs on every frame and a decorative
    # number is never worth an exception in the capture loop.
    score = getattr(obs.det, "score", None)
    if score is not None:
        out["det_score"] = round(float(score), 2)
    p_real = getattr(obs.spoof, "p_real", None)
    if p_real is not None:
        out["p_real"] = round(float(p_real), 2)
    if isinstance(obs.iqa, dict):
        for key in ("blur", "lum"):
            if obs.iqa.get(key) is not None:
                out[key] = int(round(float(obs.iqa[key])))
    # The fine pose is the one the gate at S5 uses; before that stage runs, the coarse
    # angles off the five keypoints are the best answer available.
    angles = obs.pose_fine if isinstance(obs.pose_fine, dict) else obs.pose_coarse
    if isinstance(angles, dict):
        for key in ("yaw", "pitch", "roll"):
            if angles.get(key) is not None:
                out[key] = int(round(float(angles[key])))
    # The ratios S5 actually gates on (pose.face_ratios), when the frame got that far.
    if isinstance(obs.pose_fine, dict):
        for key in ("ud", "rl"):
            if obs.pose_fine.get(key) is not None:
                out[key] = round(float(obs.pose_fine[key]), 2)
    if obs.quality is not None:
        out["quality"] = round(float(obs.quality), 2)
    return out


class Session(object):
    """Current state plus the counters a decision needs.

    session_id is owned by the runner: the machine emits CLOSE_SESSION and the runner
    clears the id once it has actually written the row. Clearing it here would make the
    close a no-op, because the action list is executed after transition() returns.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.state = IDLE
        self.session_id = None
        self.kind = None
        self.entered_at = None
        self.last_guidance = None
        self.spoof_frames = 0
        self.min_p_real = None
        self.n_good_frames = 0
        self.attempt = 0
        self.decision = None
        self.enroll_form = None
        self.enroll_error = None
        self.last_telemetry = {}

    # ------------------------------------------------------------------ helpers
    def _enter(self, state, now):
        self.state = state
        self.entered_at = now

    def _reset_counters(self):
        self.spoof_frames = 0
        self.min_p_real = None
        self.n_good_frames = 0
        self.decision = None

    def elapsed(self, now):
        return 0.0 if self.entered_at is None else now - self.entered_at

    def is_enrolling(self):
        return self.state in ENROLL_STATES

    # ------------------------------------------------------------------ events
    def _count_frame(self, outcome):
        """Fold one frame into the session counters.

        Called only after the session exists and only for frames the session actually
        processes: counting before the IDLE -> GUIDING transition would be wiped by the
        counter reset that opens the session, and frames arriving while the nurse is
        deciding belong to no session at all.
        """
        from edgeface.types import GuidanceCode

        if outcome.guidance == GuidanceCode.SPOOF_SUSPECT:
            self.spoof_frames += 1
            if outcome.obs.spoof is not None:
                p_real = outcome.obs.spoof.p_real
                self.min_p_real = p_real if self.min_p_real is None else min(
                    self.min_p_real, p_real)
        elif outcome.guidance is None:
            self.n_good_frames += 1

    def on_frame(self, outcome, now):
        """A processed frame. Returns the actions the runner must perform."""
        if (self.cfg.get("engine") or {}).get("telemetry", True):
            self.last_telemetry = telemetry(outcome, self.cfg["best_frame"]["k_max"])
        if self.is_enrolling():
            return self._on_frame_enroll(outcome, now)
        return self._on_frame_identify(outcome, now)

    def _on_frame_identify(self, outcome, now):
        from edgeface.types import GuidanceCode

        actions = []
        if self.state in (DECIDED, AWAIT_NURSE, COOLDOWN):
            return actions                      # frames are ignored while waiting

        face_present = outcome.guidance != GuidanceCode.NO_FACE

        if self.state == IDLE:
            if not face_present:
                return actions
            self.attempt += 1
            self._reset_counters()
            self._enter(GUIDING, now)
            actions.append(Action(OPEN_SESSION, {"kind": "identify"}))

        self._count_frame(outcome)

        if self.state in (GUIDING, COLLECTING):
            if not face_present and self.elapsed(now) > self.cfg["session"]["idle_after_s"]:
                actions.append(Action(CLOSE_SESSION, {"nurse_action": "cancel"}))
                actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_SUBJECT_LOST}))
                self._enter(IDLE, now)
                actions.append(Action(PUBLISH, {"state": IDLE}))
                return actions

            if outcome.collector == bf.READY:
                self._enter(DECIDED, now)
                actions.append(Action(DECIDE, {"collector": bf.READY}))
                return actions
            if outcome.collector == bf.LOW_QUALITY:
                self._enter(DECIDED, now)
                actions.append(Action(DECIDE, {"collector": bf.LOW_QUALITY}))
                return actions

            target = COLLECTING if outcome.guidance is None else GUIDING
            if target != self.state:
                self._enter(target, now)
            actions.append(Action(PUBLISH, {"state": self.state,
                                            "guidance": outcome.guidance,
                                            "telemetry": self.last_telemetry}))
        return actions

    def _on_frame_enroll(self, outcome, now):
        actions = []
        if self.state in (ENROLL_REVIEW, ENROLL_ERROR):
            return actions
        self._count_frame(outcome)
        timeout = self.cfg["enroll"]["timeout_s"]
        if self.elapsed(now) > timeout:
            self.enroll_error = "timeout"
            self._enter(ENROLL_ERROR, now)
            actions.append(Action(PUBLISH, {"state": ENROLL_ERROR, "reason": "timeout"}))
            return actions

        if outcome.collector == bf.READY:
            self._enter(ENROLL_REVIEW, now)
            actions.append(Action(SAVE_ENROLL, {"stage": "review"}))
            return actions

        target = ENROLL_COLLECTING if outcome.guidance is None else ENROLL_GUIDING
        if target != self.state:
            self._enter(target, now)
        actions.append(Action(PUBLISH, {"state": self.state, "guidance": outcome.guidance,
                                        "progress": self.n_good_frames,
                                        "total": self.cfg["enroll"]["num_templates"],
                                        "telemetry": self.last_telemetry}))
        return actions

    def on_decision(self, decision_result, now):
        """The runner ran S9/S10 and brings back the result."""
        from edgeface.types import Decision

        self.decision = decision_result
        actions = []
        if decision_result.decision is Decision.SPOOF_SUSPECT:
            actions.append(Action(SAVE_EVIDENCE, {"session_id": self.session_id}))
        self._enter(AWAIT_NURSE, now)
        # The numbers from the last frame, so the nurse screen can say why: which quality
        # gate the rejected frames missed, or how low the anti-spoofing score went. The
        # worst p_real of the attempt beats the last frame's - one convincing frame does
        # not undo the reason this session is on the alarm screen.
        numbers = dict(self.last_telemetry or {})
        if self.min_p_real is not None:
            numbers["p_real"] = round(float(self.min_p_real), 2)
        numbers["good"] = self.n_good_frames
        actions.append(Action(PUBLISH, {
            "state": AWAIT_NURSE,
            "decision": decision_result.decision.value,
            "rule_id": decision_result.rule_id,
            "candidate": decision_result.candidate,
            "telemetry": numbers,
            # Absolute deadline so the kiosk can count down without its own timer.
            "timeout_at": now + self.cfg["session"]["await_nurse_timeout_s"]}))
        return actions

    def on_command(self, command, now):
        """A nurse command from the kiosk."""
        kind = command["type"]
        payload = command.get("payload") or {}
        actions = []

        if kind == "start_enroll" and self.state in (IDLE, GUIDING, COLLECTING, COOLDOWN):
            if self.session_id is not None:
                actions.append(Action(CLOSE_SESSION, {"nurse_action": "cancel"}))
            self._reset_counters()
            self.enroll_form = payload
            self.enroll_error = None
            self._enter(ENROLL_GUIDING, now)
            actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_CONSUMED}))
            actions.append(Action(START_ENROLL, payload))
            actions.append(Action(PUBLISH, {"state": ENROLL_GUIDING}))
            return actions

        if kind == "enroll_confirm" and self.state == ENROLL_REVIEW:
            actions.append(Action(SAVE_ENROLL, {"stage": "commit", "form": self.enroll_form}))
            actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_CONSUMED}))
            self.enroll_form = None
            self._enter(COOLDOWN, now)
            actions.append(Action(PUBLISH, {"state": COOLDOWN}))
            return actions

        if kind in ("enroll_cancel", "cancel") and self.is_enrolling():
            actions.append(Action(CANCEL_ENROLL, None))
            actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_CONSUMED}))
            self.enroll_form = None
            self._enter(COOLDOWN, now)
            actions.append(Action(PUBLISH, {"state": COOLDOWN}))
            return actions

        if self.state != AWAIT_NURSE:
            return actions                        # stale command for a finished session

        if kind in ("confirm", "reject", "manual", "retry"):
            nurse_action = kind
            confirmed = payload.get("code")
            if kind == "confirm" and confirmed is None and self.decision is not None:
                candidate = self.decision.candidate
                confirmed = candidate["code"] if candidate else None
            actions.append(Action(CLOSE_SESSION, {"nurse_action": nurse_action,
                                                  "confirmed_code": confirmed,
                                                  "operator_id": payload.get("operator_id")}))
            actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_CONSUMED}))
            self._enter(COOLDOWN, now)
            actions.append(Action(PUBLISH, {"state": COOLDOWN}))
        return actions

    def on_tick(self, now):
        """Time-based transitions: nurse timeout and the cooldown pause."""
        actions = []
        session_cfg = self.cfg["session"]
        if self.state == AWAIT_NURSE and self.elapsed(now) >= session_cfg["await_nurse_timeout_s"]:
            actions.append(Action(CLOSE_SESSION, {"nurse_action": "timeout"}))
            actions.append(Action(RESET_COLLECTOR, {"reason": bf.RESET_CONSUMED}))
            self._enter(COOLDOWN, now)
            actions.append(Action(PUBLISH, {"state": COOLDOWN}))
        elif self.state == COOLDOWN and self.elapsed(now) >= session_cfg["cooldown_s"]:
            self._reset_counters()
            self._enter(IDLE, now)
            actions.append(Action(PUBLISH, {"state": IDLE}))
        elif self.state == ENROLL_ERROR and self.elapsed(now) >= session_cfg["cooldown_s"]:
            self.enroll_form = None
            self._enter(IDLE, now)
            actions.append(Action(PUBLISH, {"state": IDLE}))
        return actions

    def on_camera_error(self, now):
        actions = []
        if self.state != CAMERA_ERROR:
            if self.session_id is not None:
                actions.append(Action(CLOSE_SESSION, {"nurse_action": "cancel"}))
            self._enter(CAMERA_ERROR, now)
            actions.append(Action(PUBLISH, {"state": CAMERA_ERROR}))
        return actions

    def on_camera_ok(self, now):
        actions = []
        if self.state == CAMERA_ERROR:
            self._enter(IDLE, now)
            actions.append(Action(PUBLISH, {"state": IDLE}))
        return actions
