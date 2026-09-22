# -*- coding: utf-8 -*-
"""Kiosk logic: poll the state row, decide what to show, send nurse commands.

Imports no Qt on purpose. window.py asks this class what to draw and forwards taps back
into it, so the whole interaction can be driven from a test.
"""
import os

from edgeface.common.log import get_logger
from edgeface.kiosk import view_model
from edgeface.kiosk.auth import AdminAuth
from edgeface.storage import clock, kiosk_ipc, outbox, patients, templates
from edgeface.storage.db import get_meta, transaction

LOG = get_logger("kiosk")

# Screens the kiosk opens by itself; the rest follow the engine's state.
LOCAL_SCREENS = (view_model.SEARCH, view_model.PIN, view_model.ADMIN,
                 view_model.PATIENTS, view_model.STATUS)


class KioskController(object):
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        self.auth = AdminAuth(conn, cfg)
        self.last_seq = -1
        self.state = None
        self.last_update = None
        self.local_screen = None          # set while the nurse is in a kiosk-owned screen
        self.local_context = {}
        self.preview_path = (cfg.get("kiosk") or {}).get(
            "preview_path", "/dev/shm/edgeface/preview.jpg")

    # ------------------------------------------------------------------ polling
    def poll(self, now=None):
        """Read the state row. Returns True when something changed."""
        now = clock.now() if now is None else now
        state = kiosk_ipc.read_state(self.conn, after_seq=self.last_seq)
        if state is None:
            return False
        self.last_seq = state["seq"]
        self.state = state
        self.last_update = now
        # The engine taking over (a patient stepped up) closes a nurse-only screen.
        if self.local_screen in (view_model.SEARCH,) and state["state"] == "IDLE":
            self.local_screen = None
        return True

    def view(self, now=None):
        """The View to render right now."""
        now = clock.now() if now is None else now
        if self.local_screen == view_model.PIN:
            return self._pin_view()
        if self.local_screen == view_model.SEARCH:
            return self._search_view()
        if self.local_screen in (view_model.ADMIN, view_model.PATIENTS, view_model.STATUS):
            if not self.auth.is_unlocked(now):
                self.local_screen = view_model.PIN
                return self._pin_view()
            self.auth.touch(now)
            return self._admin_view(now)
        patient = self._candidate_patient()
        return view_model.build(self.state, now, patient, self.last_update)

    def _candidate_patient(self):
        """Local record for the candidate, so the card can show a name, not just a code."""
        payload = (self.state or {}).get("payload") or {}
        candidate = payload.get("candidate")
        if not candidate or not candidate.get("code"):
            return None
        return patients.get_with_appointment(self.conn, candidate["code"])

    def preview_bytes(self):
        """Latest preview JPEG, or None. Missing file is normal (engine may be idle)."""
        try:
            with open(self.preview_path, "rb") as f:
                return f.read()
        except (IOError, OSError):
            return None

    # ------------------------------------------------------------------ commands
    def send(self, command, payload=None, now=None):
        """Forward a nurse action to the engine, tagged with the current session."""
        now = clock.now() if now is None else now
        session_id = (self.state or {}).get("session_id")
        body = dict(payload or {})
        if self.auth.operator_id is not None:
            body.setdefault("operator_id", self.auth.operator_id)
        with transaction(self.conn):
            cmd_id = kiosk_ipc.send_command(self.conn, command, body or None, session_id, now)
        LOG.info("sent %s for session %s", command, str(session_id)[:8])
        return cmd_id

    def on_button(self, button, now=None):
        """A tap on one of the buttons of the current View."""
        now = clock.now() if now is None else now
        if button.command:
            self.send(button.command, now=now)
            return True
        if button.kind == "search":
            self.open_search()
            return True
        if button.kind == "cancel":
            self.close_local()
            return True
        return False

    # ------------------------------------------------------------------ local screens
    def open_search(self):
        self.local_screen = view_model.SEARCH
        self.local_context = {"query": "", "results": []}

    def search(self, query, now=None):
        now = clock.now() if now is None else now
        results = patients.search(self.conn, query, limit=20, now=now) if query else []
        self.local_context = {"query": query, "results": results}
        return results

    def choose_patient(self, code, now=None):
        """Manual identification: tell the engine which patient the nurse picked."""
        self.send("manual", {"code": code}, now)
        self.close_local()

    def open_pin(self):
        self.local_screen = view_model.PIN
        self.local_context = {"operator_id": None, "pin": "", "error": None}

    def unlock(self, operator_id, pin, now=None):
        ok, reason, left = self.auth.unlock(operator_id, pin, now)
        if ok:
            self.local_screen = view_model.ADMIN
            self.local_context = {}
        else:
            self.local_context = {"operator_id": operator_id, "pin": "", "error": reason,
                                  "attempts_left": left,
                                  "locked_for": self.auth.lock_remaining_s(operator_id, now)}
        return ok

    def close_local(self):
        self.local_screen = None
        self.local_context = {}

    def logout(self):
        self.auth.lock()
        self.close_local()

    def open_admin_tab(self, screen):
        if screen not in (view_model.ADMIN, view_model.PATIENTS, view_model.STATUS):
            raise ValueError("not an admin tab: {}".format(screen))
        self.local_screen = screen

    # ------------------------------------------------------------------ admin data
    def start_enroll(self, form, now=None):
        self.send("start_enroll", form, now)

    def revoke(self, code, reason="nurse", now=None):
        self.send("revoke", {"code": code, "reason": reason}, now)

    def today_patients(self, now=None):
        now = clock.now() if now is None else now
        return patients.list_active(self.conn, now)

    # ------------------------------------------------------------------ views
    def _pin_view(self):
        from edgeface.kiosk import strings

        context = self.local_context or {}
        message = strings.PIN_HINT.format(digits=self.auth.pin_length)
        severity = view_model.OK
        error = context.get("error")
        if error == "locked":
            message = strings.PIN_LOCKED.format(seconds=int(context.get("locked_for") or 0))
            severity = view_model.ALARM
        elif error:
            message = strings.PIN_WRONG.format(left=context.get("attempts_left") or 0)
            severity = view_model.ATTENTION
        return view_model.View(screen=view_model.PIN, title=strings.PIN_TITLE,
                               message=message, severity=severity,
                               buttons=(view_model.Button("cancel", strings.BTN_CANCEL, None),))

    def _search_view(self):
        from edgeface.kiosk import strings

        context = self.local_context or {}
        rows = tuple((row["patient_code"], row["full_name"]) for row in
                     context.get("results", []))
        return view_model.View(screen=view_model.SEARCH, title=strings.SEARCH_TITLE,
                               message=strings.LABEL_SEARCH, severity=view_model.OK,
                               fields=rows,
                               buttons=(view_model.Button("cancel", strings.BTN_BACK, None),))

    def _admin_view(self, now):
        from edgeface.kiosk import strings

        if self.local_screen == view_model.PATIENTS:
            rows = tuple((row["patient_code"], row["full_name"])
                         for row in self.today_patients(now))
            return view_model.View(screen=view_model.PATIENTS, title=strings.PATIENTS_TITLE,
                                   message="", severity=view_model.OK, fields=rows,
                                   buttons=(view_model.Button("cancel", strings.BTN_BACK, None),))
        if self.local_screen == view_model.STATUS:
            return view_model.View(screen=view_model.STATUS, title=strings.STATUS_TITLE,
                                   message="", severity=view_model.OK,
                                   fields=self.status_rows(now),
                                   buttons=(view_model.Button("cancel", strings.BTN_BACK, None),))
        return view_model.View(screen=view_model.ADMIN, title=strings.ADMIN_TITLE,
                               message=strings.ADMIN_LOCKED_HINT.format(
                                   seconds=int(self.auth.seconds_until_lock(now))),
                               severity=view_model.OK,
                               buttons=(view_model.Button("cancel", strings.BTN_LOGOUT, None),))

    def status_rows(self, now=None):
        """Rows for the system status tab, read straight from the shared database."""
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        last_sync = get_meta(self.conn, "last_pull_at")
        engine_state = (self.state or {}).get("state", "?")
        age = now - (self.last_update or now)
        if age > view_model.ENGINE_SILENT_S:
            engine_state = "?"
        try:
            stat = os.statvfs(os.path.dirname(self.cfg["storage"]["db_path"]) or ".")
            free_mb = stat.f_bavail * stat.f_frsize / (1024.0 * 1024.0)
        except (OSError, KeyError):
            free_mb = float("nan")
        return (
            (strings.STATUS_ROWS["engine_state"], engine_state),
            (strings.STATUS_ROWS["gallery"], str(templates.gallery_version(self.conn))),
            (strings.STATUS_ROWS["patients"], str(patients.count_active(self.conn, now))),
            (strings.STATUS_ROWS["outbox"], str(outbox.pending_count(self.conn))),
            (strings.STATUS_ROWS["last_sync"],
             strings.NEVER if not last_sync else clock.format_ts(float(last_sync))),
            (strings.STATUS_ROWS["disk_free"], "{:.0f} MB".format(free_mb)),
        )
