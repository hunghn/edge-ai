# -*- coding: utf-8 -*-
"""Turn one kiosk_state row into what the screen should show.

No Qt here: this is the layer that decides which screen, which words and which buttons,
and it is pure data in, data out, so all of it is unit-tested.
"""
from collections import namedtuple

from edgeface.kiosk import strings

# Screen ids, matching docs/plans/M6_kiosk_ui.md
IDLE = "idle"
GUIDANCE = "guidance"
CANDIDATE = "candidate"
ALERT = "alert"
SEARCH = "search"
PIN = "pin"
ADMIN = "admin"
ENROLL = "enroll"
PATIENTS = "patients"
STATUS = "status"
CHANGE_PIN = "change_pin"
SETTINGS = "settings"
DUPLICATE = "duplicate"
ERROR = "error"

# Severity drives the colour: ok (green), attention (amber), alarm (red).
OK = "ok"
ATTENTION = "attention"
ALARM = "alarm"

# kind: "confirm" | "reject" | "retry" | "search" | "cancel" | the admin menu entries
# ("enroll", "patients", "status", "change_pin", "revoke"), label: text, command: what to
# send to the engine (None when the kiosk handles it locally).
Button = namedtuple("Button", ["kind", "label", "command", "primary"])
Button.__new__.__defaults__ = (None, False)

# steps    : one of DONE/NOW/TODO per pipeline gate, for the guidance stepper
# progress : (taken, wanted) for the shot counter, or None
# chips    : ((text, tone), ...) for the app bar
# metrics  : ((label, value, tone), ...) - why a frame was turned away
# camera   : (left tag, right tag) written over the preview, or ()
# step     : which of the three enrolment steps is being worked on, or None
# Everything after session_id was added for the Material redesign and defaults to empty,
# so a View built by an older caller, or from an engine that sends no telemetry, is
# still a valid View and the page simply leaves those panels out.
View = namedtuple("View", [
    "screen", "title", "message", "severity", "buttons", "fields", "show_preview",
    "countdown_s", "session_id", "steps", "progress", "chips", "metrics", "camera",
    "step",
])
View.__new__.__defaults__ = (None, None, OK, (), (), False, None, None, (), None, (),
                             (), (), None)

# Stepper states, mirrored in widgets/stepper.py.
DONE = "done"
NOW = "now"
TODO = "todo"

# Which gate a guidance code belongs to. The code is more precise than the stage: S5
# runs both the pose check and the image quality check, and they are different steps to
# the person standing there.
STEP_OF_GUIDANCE = {
    "NO_FACE": 0, "INVALID_BBOX": 0,
    "MOVE_TO_CENTER": 1, "STEP_CLOSER": 1,
    "LOOK_STRAIGHT": 2, "EYES_CLOSED": 2, "MOUTH_OPEN": 2,
    "SPOOF_SUSPECT": 3, "TOO_DARK": 3, "TOO_BRIGHT": 3, "HOLD_STILL": 3,
    "EMBED_INVALID": 4,
}
STEP_OF_STAGE = {"S1": 0, "S2": 1, "S3": 2, "S4": 3, "S5": 3, "S6": 3, "S7": 4, "S8": 4}
N_STEPS = 5


def steps_for(guidance_code, telemetry):
    """Mark the gate being worked on, and everything before it as passed."""
    active = STEP_OF_GUIDANCE.get(guidance_code)
    if active is None:
        active = STEP_OF_STAGE.get((telemetry or {}).get("stage"))
    if active is None:
        active = N_STEPS - 1          # nothing to complain about: matching is all that's left
    return tuple(DONE if index < active else (NOW if index == active else TODO)
                 for index in range(N_STEPS))


def _limit(cfg, *path):
    node = cfg or {}
    for key in path:
        node = (node or {}).get(key) if hasattr(node, "get") else None
    return node


def quality_metrics(telemetry, cfg):
    """Each quality number against the threshold it had to clear.

    Without the config there is nothing to compare against, so the rows are left out
    rather than shown as bare numbers a nurse cannot act on.
    """
    if not telemetry or not cfg:
        return ()
    rows = []
    blur, blur_min = telemetry.get("blur"), _limit(cfg, "iqa", "blur_min")
    if blur is not None and blur_min is not None:
        passed = blur >= blur_min
        rows.append((strings.METRIC_BLUR,
                     strings.METRIC_PASSED.format(value=blur) if passed
                     else strings.METRIC_BELOW.format(value=blur, limit=int(blur_min)),
                     OK if passed else ATTENTION))
    lum = telemetry.get("lum")
    lum_min, lum_max = _limit(cfg, "iqa", "lum_min"), _limit(cfg, "iqa", "lum_max")
    if lum is not None and lum_min is not None and lum_max is not None:
        if lum < lum_min:
            rows.append((strings.METRIC_LUM,
                         strings.METRIC_BELOW.format(value=lum, limit=int(lum_min)),
                         ATTENTION))
        elif lum > lum_max:
            rows.append((strings.METRIC_LUM,
                         strings.METRIC_ABOVE.format(value=lum, limit=int(lum_max)),
                         ATTENTION))
        else:
            rows.append((strings.METRIC_LUM,
                         strings.METRIC_PASSED.format(value=lum), OK))
    yaw, yaw_max = telemetry.get("yaw"), _limit(cfg, "pose_fine", "yaw_max_deg")
    if yaw is not None and yaw_max is not None:
        passed = abs(yaw) <= yaw_max
        value = u"{}°".format(abs(yaw))
        rows.append((strings.METRIC_POSE,
                     strings.METRIC_PASSED.format(value=value) if passed
                     else strings.METRIC_ABOVE.format(value=value,
                                                      limit=int(yaw_max)),
                     OK if passed else ATTENTION))
    return tuple(rows)


def camera_tags(telemetry, show_score=True, best_frame=False):
    """The two small labels written over the preview: which frame, and how good.

    Both are diagnostics, so kiosk.show_score switches them off for a clinic where the
    screen faces the waiting room.
    """
    if not show_score:
        return ()
    left = strings.BEST_FRAME_TAG if best_frame else strings.CAMERA_TAG
    if not best_frame and telemetry.get("fps") is not None:
        left = u"{} · {}".format(left, strings.FPS_TAG.format(fps=telemetry["fps"]))
    right = ""
    if telemetry.get("quality") is not None:
        right = strings.QUALITY_TAG.format(value=telemetry["quality"])
    return (left, right)


def telemetry_of(state):
    return ((state or {}).get("payload") or {}).get("telemetry") or {}


def device_of(state):
    return ((state or {}).get("payload") or {}).get("device") or {}

ENGINE_SILENT_S = 5.0     # no state update for this long -> the engine is gone


def confidence_label(decision_value):
    return (strings.CONFIDENCE_HIGH if decision_value == "candidate_suggested"
            else strings.CONFIDENCE_LOW)


def candidate_fields(candidate, patient=None, show_score=True):
    """Rows of the candidate card. `patient` is the local record, when the kiosk has it."""
    patient = patient or {}
    fields = [(strings.LABEL_CODE, candidate.get("code") or "")]
    if patient.get("full_name"):
        fields.append((strings.LABEL_NAME, patient["full_name"]))
    if patient.get("birth_year"):
        fields.append((strings.LABEL_BIRTH_YEAR, str(patient["birth_year"])))
    if patient.get("appointment_code"):
        fields.append((strings.LABEL_APPOINTMENT, patient["appointment_code"]))
    if show_score:
        # The gap to the runner-up often says more than the top score itself: two
        # patients at 0.81 are not equally certain if one of them has nobody else close.
        if candidate.get("score") is not None:
            fields.append((strings.LABEL_SCORE, "{:.2f}".format(candidate["score"])))
        if candidate.get("margin") is not None:
            fields.append((strings.LABEL_MARGIN, "{:.2f}".format(candidate["margin"])))
    return tuple(fields)


def _idle_view():
    return View(screen=IDLE, title=strings.IDLE_TITLE, message=strings.IDLE_HINT,
                severity=OK)


def _guidance_view(state):
    message = strings.guidance(state.get("guidance_code"))
    if state["state"] == "COLLECTING" and not state.get("guidance_code"):
        message = strings.COLLECTING_HINT
    numbers = telemetry_of(state)
    kept, need = numbers.get("kept"), numbers.get("need")
    progress = (kept, need) if kept is not None and need else None
    return View(screen=GUIDANCE, title=strings.GUIDING_TITLE, message=message,
                severity=OK, show_preview=True, session_id=state.get("session_id"),
                steps=steps_for(state.get("guidance_code"), numbers),
                progress=progress, camera=camera_tags(numbers))


def _await_nurse_view(state, patient, now, show_score=True, cfg=None):
    payload = state.get("payload") or {}
    decision = payload.get("decision") or "review_required"
    candidate = payload.get("candidate")
    countdown = payload.get("timeout_at")
    countdown_s = None if countdown is None else max(0.0, countdown - now)
    numbers = telemetry_of(state)

    if decision == "spoof_suspect":
        chips = ()
        if show_score and numbers.get("p_real") is not None:
            chips = (("S4 · p_real {:.2f}".format(numbers["p_real"]), ALARM),)
        return View(screen=ALERT, title=strings.ALERT_TITLE,
                    message=strings.decision_hint(decision), severity=ALARM,
                    buttons=(Button("retry", strings.BTN_RETRY, "retry"),
                             Button("search", strings.BTN_SEARCH, None, True)),
                    countdown_s=countdown_s, session_id=state.get("session_id"),
                    chips=chips)

    if decision in ("low_quality", "no_match") or candidate is None:
        chips, metrics = (), ()
        if decision == "low_quality":
            metrics = quality_metrics(numbers, cfg)
            good, need = numbers.get("good"), numbers.get("need")
            if good is not None and need:
                chips = ((strings.GOOD_FRAMES.format(good=good, total=need),
                          ATTENTION),)
        return View(screen=ALERT, title=strings.decision_title(decision),
                    message=strings.decision_hint(decision), severity=ATTENTION,
                    buttons=(Button("retry", strings.BTN_RETRY, "retry", True),
                             Button("search", strings.BTN_SEARCH, None)),
                    countdown_s=countdown_s, session_id=state.get("session_id"),
                    show_preview=decision == "low_quality",
                    chips=chips, metrics=metrics)

    fields = candidate_fields(candidate, patient, show_score)
    fields += ((strings.LABEL_CONFIDENCE, confidence_label(decision)),)
    # The runner-up, masked. Informational while D-33 is uncalibrated; once a lookalike
    # margin is agreed this becomes a warning in its own right.
    if show_score and candidate.get("top2_code") and candidate.get("top2_score") is not None:
        from edgeface.kiosk.masking import mask_code

        fields += ((strings.LABEL_LOOKALIKE, "{}  {:.2f}".format(
            mask_code(candidate["top2_code"]), candidate["top2_score"])),)
    chips = ((strings.CHOSEN_FRAME, "primary"),)
    return View(screen=CANDIDATE, title=strings.CANDIDATE_TITLE,
                message=strings.decision_hint(decision),
                severity=OK if decision == "candidate_suggested" else ATTENTION,
                show_preview=True,
                buttons=(Button("confirm", strings.BTN_CONFIRM, "confirm", True),
                         Button("reject", strings.BTN_REJECT, "reject"),
                         Button("retry", strings.BTN_RETRY, "retry"),
                         Button("search", strings.BTN_SEARCH, None)),
                fields=fields, countdown_s=countdown_s,
                session_id=state.get("session_id"), chips=chips,
                camera=camera_tags(numbers, show_score, best_frame=True))


def _enroll_view(state):
    payload = state.get("payload") or {}
    engine_state = state["state"]
    if engine_state == "ENROLL_ERROR":
        reason = payload.get("reason") or state.get("guidance_code")
        return View(screen=ENROLL, title=strings.ENROLL_TITLE,
                    message=strings.ENROLL_ERRORS.get(reason, strings.ENROLL_ERRORS["timeout"]),
                    severity=ATTENTION,
                    buttons=(Button("cancel", strings.BTN_BACK_TO_MENU, None),),
                    step=1)
    if engine_state == "ENROLL_REVIEW":
        warnings = payload.get("warnings") or []
        duplicates = payload.get("duplicates") or []
        if duplicates and ("duplicate_face" in warnings
                           or "duplicate_unknown_threshold" in warnings):
            return _duplicate_view(payload, warnings, duplicates)
        lines = []
        if "duplicate_face" in warnings:
            lines.append(strings.ENROLL_DUPLICATE.format(code=payload.get("duplicate_code")))
        if "duplicate_unknown_threshold" in warnings:
            lines.append(strings.ENROLL_DUPLICATE_UNKNOWN.format(
                code=payload.get("duplicate_code")))
        if "inconsistent_capture" in warnings:
            lines.append(strings.ENROLL_INCONSISTENT)
        message = "\n".join(lines) if lines else strings.LABEL_PROGRESS.format(
            done=payload.get("n_templates", 0), total=payload.get("n_templates", 0))
        return View(screen=ENROLL, title=strings.ENROLL_TITLE, message=message,
                    severity=ATTENTION if lines else OK,
                    buttons=(Button("enroll_confirm", strings.BTN_ENROLL_SAVE,
                                    "enroll_confirm", True),
                             Button("enroll_cancel", strings.BTN_ENROLL_CANCEL,
                                    "enroll_cancel")),
                    fields=(("", strings.LABEL_PROGRESS.format(
                        done=payload.get("n_templates", 0),
                        total=payload.get("n_templates", 0))),),
                    step=2, metrics=_review_metrics(payload),
                    progress=(payload.get("n_templates", 0),
                              payload.get("n_templates", 0)))
    done = payload.get("progress", 0)
    total = payload.get("total", 5)
    message = strings.guidance(state.get("guidance_code")) if state.get("guidance_code") \
        else strings.COLLECTING_HINT
    return View(screen=ENROLL, title=strings.ENROLL_TITLE, message=message, severity=OK,
                show_preview=True,
                fields=(("", strings.LABEL_PROGRESS.format(done=done, total=total)),),
                buttons=(Button("enroll_cancel", strings.BTN_ENROLL_CANCEL,
                                "enroll_cancel"),),
                step=1, progress=(done, total),
                camera=camera_tags(telemetry_of(state)))


def _review_metrics(payload):
    """What the five shots came out like, for the nurse to sign off on."""
    rows = []
    if payload.get("self_consistency") is not None:
        rows.append((strings.ENROLL_CONSISTENCY,
                     "{:.2f}".format(payload["self_consistency"]), OK))
    if payload.get("n_templates"):
        rows.append((strings.ENROLL_TEMPLATES,
                     u"{} \u00d7 512-d".format(payload["n_templates"]), OK))
    return tuple(rows)


def _duplicate_view(payload, warnings, duplicates):
    """The warning screen: masked codes, scores, and a face for each one.

    The faces are not in this View - it carries text only. The page reads them from the
    database itself, so a picture never travels through the kiosk_state row.
    """
    from edgeface.kiosk.masking import mask_code

    rows = tuple((mask_code(entry.get("code")), "{:.2f}".format(entry["score"]))
                 for entry in duplicates if entry.get("score") is not None)
    message = (strings.DUPLICATE_UNCALIBRATED
               if "duplicate_unknown_threshold" in warnings else strings.DUPLICATE_HINT)
    return View(screen=DUPLICATE, title=strings.DUPLICATE_TITLE, message=message,
                severity=ATTENTION, fields=rows, show_preview=True,
                buttons=(Button("enroll_confirm", strings.BTN_SAVE_ANYWAY_LONG,
                                "enroll_confirm"),
                         Button("enroll_cancel", strings.BTN_CANCEL_AND_LOOKUP,
                                "enroll_cancel", True)))


def lookalike_code(state):
    """The runner-up's real code, so the kiosk can fetch that one face. Never displayed."""
    payload = (state or {}).get("payload") or {}
    return ((payload.get("candidate") or {}).get("top2_code")) or None


def duplicate_codes(state):
    """The real (unmasked) codes the duplicate page needs to fetch faces for."""
    payload = (state or {}).get("payload") or {}
    return [entry.get("code") for entry in (payload.get("duplicates") or [])
            if entry.get("code")]


def build(state, now, patient=None, last_update=None, show_score=True, cfg=None):
    """kiosk_state row -> View. `state` may be None when nothing was ever published.

    `cfg` is the pipeline config, so a quality number can be shown against the threshold
    it had to clear. Without it those rows are simply left out - a bare "độ nét 41" is
    not something a nurse can act on.
    """
    if state is None:
        return View(screen=ERROR, title=strings.ERROR_TITLE,
                    message=strings.STATUS_ENGINE_DOWN, severity=ALARM)

    age = now - (last_update if last_update is not None else state.get("updated_at", now))
    if age > ENGINE_SILENT_S:
        return View(screen=ERROR, title=strings.ERROR_TITLE,
                    message=strings.STATUS_ENGINE_DOWN, severity=ALARM,
                    chips=((strings.SILENT_FOR.format(seconds=int(age)), ALARM),))

    engine_state = state["state"]
    if engine_state == "CAMERA_ERROR":
        return View(screen=ERROR, title=strings.ERROR_TITLE, message=strings.STATUS_CAMERA,
                    severity=ALARM)
    if engine_state.startswith("ENROLL"):
        return _enroll_view(state)
    if engine_state == "AWAIT_NURSE":
        return _await_nurse_view(state, patient, now, show_score, cfg)
    if engine_state in ("GUIDING", "COLLECTING", "DECIDED"):
        return _guidance_view(state)
    return _idle_view()
