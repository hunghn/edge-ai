# -*- coding: utf-8 -*-
"""PIN gate for the admin screen, plus the inactivity lock.

The counting and lockout live in storage.operators (shared with any other process that
might check a PIN); this class adds the part that is specific to a screen: staying
unlocked only while someone is touching it.
"""
from edgeface.storage import clock, operators
from edgeface.storage.db import transaction


class AdminAuth(object):
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        auth_cfg = cfg.get("auth") or {}
        self.pin_length = int(auth_cfg.get("pin_length", 6))
        self.max_failed = int(auth_cfg.get("max_failed_attempts", 5))
        self.lockout_s = float(auth_cfg.get("lockout_s", 300))
        self.idle_lock_s = float((cfg.get("session") or {}).get("admin_lock_s", 60))
        self.operator_id = None
        self.last_activity = None

    # ------------------------------------------------------------------ state
    def is_unlocked(self, now=None):
        now = clock.now() if now is None else now
        if self.operator_id is None:
            return False
        if self.last_activity is not None and (now - self.last_activity) > self.idle_lock_s:
            self.lock()
            return False
        return True

    def touch(self, now=None):
        """Any interaction postpones the automatic lock."""
        self.last_activity = clock.now() if now is None else now

    def lock(self):
        self.operator_id = None
        self.last_activity = None

    def seconds_until_lock(self, now=None):
        if self.operator_id is None or self.last_activity is None:
            return 0.0
        now = clock.now() if now is None else now
        return max(0.0, self.idle_lock_s - (now - self.last_activity))

    # ------------------------------------------------------------------ PIN
    def operators(self):
        return operators.list_active(self.conn)

    def unlock(self, operator_id, pin, now=None):
        """(ok, reason, attempts_left). attempts_left is None when not applicable."""
        now = clock.now() if now is None else now
        if len(pin or "") != self.pin_length:
            return False, "bad_format", None
        with transaction(self.conn):
            ok, reason = operators.verify(self.conn, operator_id, pin, now,
                                          self.max_failed, self.lockout_s)
        if ok:
            self.operator_id = operator_id
            self.touch(now)
            return True, reason, None
        row = operators.get(self.conn, operator_id) or {}
        left = max(0, self.max_failed - int(row.get("failed_attempts") or 0))
        return False, reason, (None if reason == operators.ERR_LOCKED else left)

    def lock_remaining_s(self, operator_id, now=None):
        now = clock.now() if now is None else now
        row = operators.get(self.conn, operator_id) or {}
        until = row.get("locked_until")
        return 0.0 if not until else max(0.0, until - now)

    def change_pin(self, old_pin, new_pin, now=None):
        if self.operator_id is None:
            return False, "locked"
        now = clock.now() if now is None else now
        with transaction(self.conn):
            ok, reason = operators.change_pin(
                self.conn, self.operator_id, old_pin, new_pin, now,
                iterations=(self.cfg.get("auth") or {}).get("pbkdf2_iterations", 100000),
                pin_length=self.pin_length, max_failed=self.max_failed,
                lockout_s=self.lockout_s)
        if ok:
            self.touch(now)
        return ok, reason
