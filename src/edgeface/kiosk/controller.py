# -*- coding: utf-8 -*-
"""Kiosk logic: poll the state row, decide what to show, send nurse commands.

Imports no Qt on purpose. window.py asks this class what to draw and forwards taps back
into it, so the whole interaction can be driven from a test.
"""
import os

from edgeface.common.log import get_logger
from edgeface.kiosk import view_model
from edgeface.kiosk.auth import AdminAuth
from edgeface.storage import (clock, faces, kiosk_ipc, operators, outbox, patients,
                              templates)
from edgeface.storage.db import get_meta, set_meta, transaction

LOG = get_logger("kiosk")

# Screens the kiosk opens by itself; the rest follow the engine's state.
LOCAL_SCREENS = (view_model.SEARCH, view_model.PIN, view_model.ADMIN,
                 view_model.PATIENTS, view_model.STATUS, view_model.CHANGE_PIN)

# The screens that sit behind the PIN. Leaving one of them locks the admin session.
ADMIN_SCREENS = (view_model.ADMIN, view_model.PATIENTS, view_model.STATUS,
                 view_model.CHANGE_PIN)


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
        self._preview_token = None

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
        if self.local_screen in ADMIN_SCREENS:
            # Taking a patient's five enrolment shots takes longer than the lock timeout
            # and the nurse is watching the patient, not the screen. Locking there would
            # throw away the whole attempt, so the capture itself counts as activity.
            if self._enrolling():
                self.auth.touch(now)
                # Hand the screen to the engine while it photographs the patient: the
                # admin menu must not sit on top of the pose guidance, the shot counter
                # or the Save button. The admin session stays unlocked underneath.
                return view_model.build(self.state, now, None, self.last_update,
                                        cfg=self.cfg)
            if not self.auth.is_unlocked(now):
                self.local_screen = view_model.PIN
                self.local_context = {"operator_id": None, "pin": "", "error": None}
                return self._pin_view()
            # No touch() here on purpose: window.refresh() runs ten times a second, so
            # touching from the draw path would reset the timer forever and the screen
            # would never lock. Only real taps and keystrokes call touch().
            if self.local_screen == view_model.CHANGE_PIN:
                return self._change_pin_view()
            return self._admin_view(now)
        patient = self._candidate_patient()
        show_score = (self.cfg.get("kiosk") or {}).get("show_score", True)
        return view_model.build(self.state, now, patient, self.last_update, show_score,
                                self.cfg)

    def _enrolling(self):
        """True while the engine is running the enrolment flow."""
        return str((self.state or {}).get("state") or "").startswith("ENROLL")

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

    def preview_changed(self):
        """True when the engine has written a new frame since the last time we asked.

        Reading, decoding and repainting an image the viewer is already looking at is
        pure waste, and at fifteen frames a second there is no room for it. The engine
        publishes with os.rename, so the modification time moves with every new picture.
        """
        try:
            stat = os.stat(self.preview_path)
            token = (stat.st_mtime, stat.st_size)
        except OSError:
            token = None
        if token == self._preview_token:
            return False
        self._preview_token = token
        return token is not None

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
        self.touch(now)
        if button.command:
            self.send(button.command, now=now)
            return True
        if button.kind == "search":
            self.open_search()
            return True
        if button.kind in ("patients", "status"):
            self.open_admin_tab(button.kind)
            return True
        if button.kind == "change_pin":
            self.open_change_pin()
            return True
        if button.kind == "logout":
            # The rail's way out means out, from wherever it is tapped. "cancel" is the
            # back button, which inside the admin area means up to the menu.
            self.logout()
            return True
        if button.kind == "sync":
            self.request_sync(now)
            return True
        if button.kind == "revoke":
            code = (self.local_context or {}).get("selected")
            if code:
                self.revoke_patient(code, now=now)
            return True
        if button.kind == "cancel":
            # Inside the admin area, Back means "up to the menu", not "log out".
            if self.local_screen in (view_model.PATIENTS, view_model.STATUS,
                                     view_model.CHANGE_PIN):
                self.open_admin_tab(view_model.ADMIN)
            else:
                self.close_local()
            return True
        # "enroll" is handled in window.py: the form is a widget, not a View.
        return False

    def touch(self, now=None):
        """Record nurse activity, so the admin screen locks on idleness, not on drawing."""
        if self.auth.is_unlocked(now):
            self.auth.touch(now)

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
        if screen not in ADMIN_SCREENS:
            raise ValueError("not an admin tab: {}".format(screen))
        self.local_screen = screen
        self.local_context = {}

    def open_change_pin(self):
        self.local_screen = view_model.CHANGE_PIN
        self.local_context = {"step": "old", "old": None, "new": None, "error": None}

    def submit_change_pin(self, pin, now=None):
        """One step of old -> new -> repeat. Returns the step now being asked for.

        The repeat step is not politeness: one wrong digit in the 'new' step would lock
        the nurse out of the kiosk, and there is no way back in from the kiosk itself.
        """
        from edgeface.kiosk import strings

        context = dict(self.local_context or {})
        step = context.get("step", "old")
        context["error"] = None

        if step == "old":
            context["old"], context["step"] = pin, "new"
        elif step == "new":
            if not operators.validate_pin_format(pin, self.auth.pin_length):
                context["error"] = strings.CHANGE_PIN_BAD_FORMAT.format(
                    digits=self.auth.pin_length)
            else:
                context["new"], context["step"] = pin, "repeat"
        else:
            if pin != context.get("new"):
                # Back to the start: we do not know which of the two was the typo.
                context.update({"step": "new", "new": None,
                                "error": strings.CHANGE_PIN_MISMATCH})
            else:
                ok, reason = self.auth.change_pin(context["old"], pin, now)
                if ok:
                    LOG.info("operator %s changed their PIN", self.auth.operator_id)
                    self.local_screen = view_model.ADMIN
                    self.local_context = {"notice": strings.CHANGE_PIN_SAVED}
                    return "done"
                # A wrong old PIN counts as a failed attempt in operators.verify(), so
                # repeated guesses here lock the account just like the unlock screen.
                context.update({
                    "step": "old", "old": None, "new": None,
                    "error": (strings.CHANGE_PIN_BAD_FORMAT.format(digits=self.auth.pin_length)
                              if reason == "bad_format" else strings.CHANGE_PIN_WRONG_OLD)})
        self.local_context = context
        return context["step"]

    # ------------------------------------------------------------------ admin data
    def start_enroll(self, form, now=None):
        self.send("start_enroll", form, now)

    def select_patient(self, code):
        """Remember which row of the patient list is highlighted, so Revoke has a target."""
        context = dict(self.local_context or {})
        context["selected"] = code
        context.pop("notice", None)
        self.local_context = context

    def request_sync(self, now=None):
        """Ask the sync process for a pull. It clears the flag once it has seen it.

        Not a command to the engine: the engine has nothing to do with the server, and
        sync already reads this database on every cycle.
        """
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        with transaction(self.conn):
            set_meta(self.conn, "sync_requested_at", now)
        self.local_context = dict(self.local_context or {},
                                  notice=strings.SYNC_REQUESTED)
        LOG.info("nurse asked for a sync")
        return True

    def revoke_patient(self, code, reason="nurse", now=None):
        """Revoke locally, the way sync/puller.py does it.

        Not a command to the engine: the engine has no revoke action, and the gallery is
        reloaded from the database anyway. Bumping the version is what makes the engine
        notice, through the refresh_if_changed() call already in its loop.
        """
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        with transaction(self.conn):
            patients.revoke(self.conn, code, reason, now)
            patients.delete(self.conn, code)
            templates.bump_gallery_version(self.conn)
        LOG.warning("nurse revoked patient %s", code)
        self.local_context = {"notice": strings.REVOKE_DONE.format(code=code)}
        return True

    def duplicate_faces(self):
        """Pictures for the duplicate warning, in the engine's order, None where missing.

        A list rather than a dict keyed by code: the View carries masked codes, so the
        page can only pair a face with a row by position, and a dict would both reorder
        the rows and silently drop the patients who have no picture - putting one
        patient's face beside another patient's code on the one screen where that would
        be worst.

        The codes come from the state row; the pictures are read from the database here
        in the kiosk process, so no face is ever written into kiosk_state.
        """
        codes = view_model.duplicate_codes(self.state)
        if not codes:
            return []
        found = faces.get_many(self.conn, codes)
        return [found.get(code) for code in codes]

    def today_patients(self, now=None):
        now = clock.now() if now is None else now
        return patients.list_active(self.conn, now)

    def admin_summary(self, now=None):
        """The number under each admin card, so a nurse often need not open it."""
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        rows = self.today_patients(now)
        from_kiosk = len([r for r in rows if r["source"] == patients.SOURCE_KIOSK])
        pending = outbox.pending_count(self.conn)
        engine_state = (self.state or {}).get("state", "?")
        if now - (self.last_update or now) > view_model.ENGINE_SILENT_S:
            engine_state = "?"
        return {
            "enroll": strings.ENROLL_CARD_HINT,
            "patients": u"{} · {}".format(
                strings.PATIENTS_ACTIVE_SHORT.format(n=len(rows)),
                strings.FROM_KIOSK.format(n=from_kiosk)),
            "status": u"{} · {}".format(
                strings.ENGINE_IS.format(state=engine_state),
                strings.OUTBOX_PENDING.format(n=pending)),
            "change_pin": self._pin_age(now),
        }

    def _pin_age(self, now):
        from edgeface.kiosk import strings

        if self.auth.operator_id is None:
            return strings.PIN_NEVER_CHANGED
        row = operators.get(self.conn, self.auth.operator_id)
        changed = row["pin_changed_at"] if row is not None else None
        if not changed:
            return strings.PIN_NEVER_CHANGED
        return strings.PIN_CHANGED_AGO.format(n=int((now - float(changed)) / 86400))

    def patient_rows(self, now=None):
        """What the patient list draws per row, beyond the code and the name.

        Where the record came from and when it expires are the two things a nurse asks
        about a row, and neither is in the (code, name) pairs the View carries.
        """
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        counts = templates.count_by_patient(self.conn)
        rows = {}
        for patient in self.today_patients(now):
            code = patient["patient_code"]
            source = (strings.SOURCE_KIOSK if patient["source"] == patients.SOURCE_KIOSK
                      else strings.SOURCE_SERVER)
            rows[code] = {
                "sub": u"{} · {} · {}".format(
                    code, source,
                    strings.TEMPLATE_COUNT.format(n=counts.get(code, 0))),
                "trailing": strings.EXPIRES_AT.format(
                    at=clock.format_ts(patient["expires_at"])[11:16]),
                "trash": True,
            }
        return rows

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

        context = self.local_context or {}

        if self.local_screen == view_model.PATIENTS:
            rows = tuple((row["patient_code"], row["full_name"])
                         for row in self.today_patients(now))
            selected = context.get("selected")
            buttons = [view_model.Button("cancel", strings.BTN_BACK_TO_MENU, None)]
            if selected:
                buttons.insert(0, view_model.Button("revoke", strings.BTN_REVOKE, None))
            if context.get("notice"):
                message, severity = context["notice"], view_model.OK
            elif not rows:
                message, severity = strings.PATIENTS_EMPTY, view_model.ATTENTION
            elif selected:
                message = strings.REVOKE_CONFIRM.format(code=selected)
                severity = view_model.ATTENTION
            else:
                message, severity = strings.REVOKE_PICK, view_model.OK
            return view_model.View(screen=view_model.PATIENTS, title=strings.PATIENTS_TITLE,
                                   message=message, severity=severity, fields=rows,
                                   buttons=tuple(buttons))

        if self.local_screen == view_model.STATUS:
            # The sync request is confirmed here or nowhere: it is the only thing on
            # this screen a nurse can set off, and it has nothing else to show for it.
            return view_model.View(screen=view_model.STATUS, title=strings.STATUS_TITLE,
                                   message=context.get("notice") or "",
                                   severity=view_model.OK,
                                   fields=self.status_rows(now),
                                   buttons=(view_model.Button("cancel",
                                                              strings.BTN_BACK_TO_MENU,
                                                              None),
                                            view_model.Button("sync",
                                                              strings.BTN_SYNC_NOW,
                                                              None),))

        # The admin landing screen: the menu. Without these four buttons the screen is a
        # dead end, which is exactly the bug this replaced.
        return view_model.View(
            screen=view_model.ADMIN, title=strings.ADMIN_TITLE,
            message=context.get("notice") or strings.ADMIN_LOCKED_HINT.format(
                seconds=int(self.auth.seconds_until_lock(now))),
            severity=view_model.OK,
            buttons=(
                view_model.Button("enroll", strings.BTN_MENU_ENROLL, None, True),
                view_model.Button("patients", strings.BTN_MENU_PATIENTS, None),
                view_model.Button("status", strings.BTN_MENU_STATUS, None),
                view_model.Button("change_pin", strings.BTN_CHANGE_PIN, None),
                view_model.Button("cancel", strings.BTN_LOGOUT, None),
            ))

    def _change_pin_view(self):
        from edgeface.kiosk import strings

        context = self.local_context or {}
        prompts = {"old": strings.CHANGE_PIN_OLD, "new": strings.CHANGE_PIN_NEW,
                   "repeat": strings.CHANGE_PIN_REPEAT}
        error = context.get("error")
        return view_model.View(
            screen=view_model.CHANGE_PIN, title=strings.CHANGE_PIN_TITLE,
            message=error or prompts.get(context.get("step", "old"), strings.CHANGE_PIN_OLD),
            severity=view_model.ATTENTION if error else view_model.OK,
            buttons=(view_model.Button("cancel", strings.BTN_BACK_TO_MENU, None),))

    def status_tiles(self, now=None):
        """(label, value, supporting line, tone) for the status screen.

        A number on its own does not say whether it is good news: "0" is an empty outbox
        and "4.2 GB" is plenty of room, and a nurse should not have to know which way is
        up. The tone is what makes the screen readable at a glance.
        """
        from edgeface.kiosk import strings

        now = clock.now() if now is None else now
        last_sync = get_meta(self.conn, "last_pull_at")
        engine_state = (self.state or {}).get("state", "?")
        age = now - (self.last_update or now)
        silent = age > view_model.ENGINE_SILENT_S
        if silent:
            engine_state = "?"
        free_mb, free_pct = float("nan"), None
        try:
            stat = os.statvfs(os.path.dirname(self.cfg["storage"]["db_path"]) or ".")
            free_mb = stat.f_bavail * stat.f_frsize / (1024.0 * 1024.0)
            if stat.f_blocks:
                free_pct = int(round(100.0 * stat.f_bavail / stat.f_blocks))
        except (OSError, KeyError, ZeroDivisionError):
            pass
        pending = outbox.pending_count(self.conn)
        device = view_model.device_of(self.state)
        numbers = view_model.telemetry_of(self.state)

        tiles = [
            (strings.STATUS_ROWS["engine_state"], engine_state,
             strings.NEVER if silent else strings.HEARTBEAT_AGO.format(s=round(age, 1)),
             view_model.ALARM if silent else view_model.OK),
            (strings.STATUS_ROWS["fps"],
             "{:.1f}".format(numbers["fps"]) if numbers.get("fps") is not None
             else strings.NEVER, strings.FPS_TARGET, None),
            (strings.STATUS_ROWS["gallery"], "v" + str(templates.gallery_version(self.conn)),
             strings.GALLERY_FOOT, None),
            (strings.STATUS_ROWS["patients"],
             str(patients.count_active(self.conn, now)), strings.PATIENTS_FOOT, None),
            (strings.STATUS_ROWS["outbox"], str(pending),
             strings.OUTBOX_EMPTY if not pending else strings.OUTBOX_WAITING.format(
                 s=int(outbox.oldest_pending_age(self.conn, now))),
             view_model.OK if not pending else view_model.ATTENTION),
            (strings.STATUS_ROWS["last_sync"],
             strings.NEVER if not last_sync else clock.format_ts(float(last_sync))[11:16],
             "" if not last_sync else strings.MINUTES_AGO.format(
                 n=int((now - float(last_sync)) / 60)), None),
            (strings.STATUS_ROWS["disk_free"], "{:.1f} GB".format(free_mb / 1024.0),
             "" if free_pct is None else strings.DISK_FOOT.format(pct=free_pct),
             None if free_pct is None or free_pct > 10 else view_model.ATTENTION),
        ]
        if device.get("ram_mb"):
            total = device.get("ram_total_mb") or 0
            tiles.append((strings.STATUS_ROWS["ram"], str(device["ram_mb"]),
                          strings.RAM_FOOT.format(total=total) if total else "", None))
        if device.get("temp_c"):
            tiles.append((strings.STATUS_ROWS["temp"],
                          u"{}°C".format(device["temp_c"]),
                          strings.TEMP_FOOT, None))
        return tuple(tiles)

    def device_line(self):
        """One line naming the board, for the bottom of the status screen."""
        from edgeface.kiosk import strings

        device = view_model.device_of(self.state)
        parts = [strings.BOARD_NAME]
        if device.get("ram_mb") and device.get("ram_total_mb"):
            parts.append(u"RAM {} / {} MB".format(device["ram_mb"],
                                                  device["ram_total_mb"]))
        if device.get("cpu_pct") is not None:
            parts.append(u"CPU {}%".format(device["cpu_pct"]))
        parts.append(str((self.cfg.get("kiosk") or {}).get("device_name", "KIOSK")))
        return u"  ·  ".join(parts)

    def status_rows(self, now=None):
        """The status tab as plain (label, value) pairs, for the generic field table."""
        return tuple((label, value) for label, value, _foot, _tone
                     in self.status_tiles(now))
