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

View = namedtuple("View", [
    "screen", "title", "message", "severity", "buttons", "fields", "show_preview",
    "countdown_s", "session_id",
])
View.__new__.__defaults__ = (None, None, OK, (), (), False, None, None)

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
    return View(screen=GUIDANCE, title=strings.GUIDING_TITLE, message=message,
                severity=OK, show_preview=True, session_id=state.get("session_id"))


def _await_nurse_view(state, patient, now, show_score=True):
    payload = state.get("payload") or {}
    decision = payload.get("decision") or "review_required"
    candidate = payload.get("candidate")
    countdown = payload.get("timeout_at")
    countdown_s = None if countdown is None else max(0.0, countdown - now)

    if decision == "spoof_suspect":
        return View(screen=ALERT, title=strings.ALERT_TITLE,
                    message=strings.decision_hint(decision), severity=ALARM,
                    buttons=(Button("retry", strings.BTN_RETRY, "retry"),
                             Button("search", strings.BTN_SEARCH, None)),
                    countdown_s=countdown_s, session_id=state.get("session_id"))

    if decision in ("low_quality", "no_match") or candidate is None:
        return View(screen=ALERT, title=strings.decision_title(decision),
                    message=strings.decision_hint(decision), severity=ATTENTION,
                    buttons=(Button("retry", strings.BTN_RETRY, "retry", True),
                             Button("search", strings.BTN_SEARCH, None)),
                    countdown_s=countdown_s, session_id=state.get("session_id"))

    fields = candidate_fields(candidate, patient, show_score)
    fields += ((strings.LABEL_CONFIDENCE, confidence_label(decision)),)
    # The runner-up, masked. Informational while D-33 is uncalibrated; once a lookalike
    # margin is agreed this becomes a warning in its own right.
    if show_score and candidate.get("top2_code") and candidate.get("top2_score") is not None:
        from edgeface.kiosk.masking import mask_code

        fields += ((strings.LABEL_LOOKALIKE, "{}  {:.2f}".format(
            mask_code(candidate["top2_code"]), candidate["top2_score"])),)
    return View(screen=CANDIDATE, title=strings.CANDIDATE_TITLE,
                message=strings.decision_hint(decision),
                severity=OK if decision == "candidate_suggested" else ATTENTION,
                show_preview=True,
                buttons=(Button("confirm", strings.BTN_CONFIRM, "confirm", True),
                         Button("reject", strings.BTN_REJECT, "reject"),
                         Button("retry", strings.BTN_RETRY, "retry"),
                         Button("search", strings.BTN_SEARCH, None)),
                fields=fields, countdown_s=countdown_s,
                session_id=state.get("session_id"))


def _enroll_view(state):
    payload = state.get("payload") or {}
    engine_state = state["state"]
    if engine_state == "ENROLL_ERROR":
        reason = payload.get("reason") or state.get("guidance_code")
        return View(screen=ENROLL, title=strings.ENROLL_TITLE,
                    message=strings.ENROLL_ERRORS.get(reason, strings.ENROLL_ERRORS["timeout"]),
                    severity=ATTENTION,
                    buttons=(Button("cancel", strings.BTN_BACK, None),))
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
                             Button("enroll_cancel", strings.BTN_CANCEL, "enroll_cancel")),
                    fields=(("", strings.LABEL_PROGRESS.format(
                        done=payload.get("n_templates", 0),
                        total=payload.get("n_templates", 0))),))
    done = payload.get("progress", 0)
    total = payload.get("total", 5)
    message = strings.guidance(state.get("guidance_code")) if state.get("guidance_code") \
        else strings.COLLECTING_HINT
    return View(screen=ENROLL, title=strings.ENROLL_TITLE, message=message, severity=OK,
                show_preview=True,
                fields=(("", strings.LABEL_PROGRESS.format(done=done, total=total)),),
                buttons=(Button("enroll_cancel", strings.BTN_CANCEL, "enroll_cancel"),))


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
                severity=ATTENTION, fields=rows,
                buttons=(Button("enroll_confirm", strings.BTN_SAVE_ANYWAY, "enroll_confirm"),
                         Button("enroll_cancel", strings.BTN_CANCEL, "enroll_cancel", True)))


def lookalike_code(state):
    """The runner-up's real code, so the kiosk can fetch that one face. Never displayed."""
    payload = (state or {}).get("payload") or {}
    return ((payload.get("candidate") or {}).get("top2_code")) or None


def duplicate_codes(state):
    """The real (unmasked) codes the duplicate page needs to fetch faces for."""
    payload = (state or {}).get("payload") or {}
    return [entry.get("code") for entry in (payload.get("duplicates") or [])
            if entry.get("code")]


def build(state, now, patient=None, last_update=None, show_score=True):
    """kiosk_state row -> View. `state` may be None when nothing was ever published."""
    if state is None:
        return View(screen=ERROR, title=strings.ERROR_TITLE,
                    message=strings.STATUS_ENGINE_DOWN, severity=ALARM)

    age = now - (last_update if last_update is not None else state.get("updated_at", now))
    if age > ENGINE_SILENT_S:
        return View(screen=ERROR, title=strings.ERROR_TITLE,
                    message=strings.STATUS_ENGINE_DOWN, severity=ALARM)

    engine_state = state["state"]
    if engine_state == "CAMERA_ERROR":
        return View(screen=ERROR, title=strings.ERROR_TITLE, message=strings.STATUS_CAMERA,
                    severity=ALARM)
    if engine_state.startswith("ENROLL"):
        return _enroll_view(state)
    if engine_state == "AWAIT_NURSE":
        return _await_nurse_view(state, patient, now, show_score)
    if engine_state in ("GUIDING", "COLLECTING", "DECIDED"):
        return _guidance_view(state)
    return _idle_view()
