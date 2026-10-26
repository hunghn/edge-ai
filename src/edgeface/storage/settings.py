"""Values a nurse can change on the kiosk admin screen, on top of the YAML config.

Only the keys listed under `admin_settings` in the config can be changed, and only within
the range given there. The YAML stays the default: a key with no saved value uses it,
and "Khôi phục mặc định" deletes the saved value.

Stored in gallery_meta, the key/value table the processes already share, as
`setting.<dotted key>`. "none" is a deliberate empty value ("Không xét"), which is not
the same as nothing saved. Who changed it, and when, is kept next to the value for the
screen, and every change also goes to the outbox so the server has the audit trail.

The engine reads these at every decision (settings.effective), so a change applies from
the next person on, without a restart.
"""
from edgeface import config as cfg_mod
from edgeface.storage import clock
from edgeface.storage.db import get_meta, transaction
from edgeface.storage.outbox import enqueue

PREFIX = "setting."
NONE = "none"


def _key(key, suffix=""):
    return PREFIX + key + suffix


def _decode(raw):
    if raw is None or raw == NONE:
        return None
    return float(raw)


def editable_keys(cfg):
    return tuple(sorted((cfg_mod.get(cfg, "admin_settings", None) or {}).keys()))


def overrides(conn, cfg):
    """{dotted key: value} for every editable key that has a saved value."""
    out = {}
    for key in editable_keys(cfg):
        raw = get_meta(conn, _key(key))
        if raw is not None:
            out[key] = _decode(raw)
    return out


def describe(conn, cfg, key):
    """{'value', 'default', 'saved', 'updated_at', 'operator_id'} for the admin screen."""
    raw = get_meta(conn, _key(key))
    updated_at = get_meta(conn, _key(key, ".updated_at"))
    operator_id = get_meta(conn, _key(key, ".operator_id"))
    default = cfg_mod.get(cfg, key, None)
    return {"value": default if raw is None else _decode(raw), "default": default,
            "saved": raw is not None,
            "updated_at": float(updated_at) if updated_at else None,
            "operator_id": int(operator_id) if operator_id else None}


def effective(cfg, conn):
    """The config with the saved values applied. Unchanged config when there are none.

    A saved value the current config no longer allows (the range was narrowed in the
    YAML after it was saved) is ignored rather than allowed to stop the engine.
    """
    saved = {}
    for key, value in overrides(conn, cfg).items():
        try:
            cfg_mod.check_admin_value(cfg, key, value)
        except ValueError:
            continue
        saved[key] = value
    if not saved:
        return cfg
    return cfg_mod.with_overrides(cfg, saved)


def _write(conn, key, raw, operator_id, now):
    for suffix, value in (("", raw), (".updated_at", now), (".operator_id", operator_id)):
        name = _key(key, suffix)
        if value is None:
            conn.execute("DELETE FROM gallery_meta WHERE key = ?", (name,))
        else:
            conn.execute("INSERT OR REPLACE INTO gallery_meta (key, value) VALUES (?, ?)",
                         (name, str(value)))


def set_value(conn, cfg, key, value, operator_id=None, now=None):
    """Save one value. Raises ValueError when admin_settings does not allow it."""
    now = clock.now() if now is None else now
    if value is not None:
        value = round(float(value), 4)
    cfg_mod.check_admin_value(cfg, key, value)
    with transaction(conn):
        old = describe(conn, cfg, key)["value"]
        _write(conn, key, NONE if value is None else repr(value), operator_id, now)
        enqueue(conn, "settings.changed", {"key": key, "old": old, "new": value,
                                           "operator_id": operator_id}, at=now)
    return value


def reset(conn, cfg, key, operator_id=None, now=None):
    """Forget the saved value: the YAML default applies again."""
    now = clock.now() if now is None else now
    if key not in editable_keys(cfg):
        raise ValueError("{} cannot be changed from the admin screen".format(key))
    with transaction(conn):
        before = describe(conn, cfg, key)
        if not before["saved"]:
            return before["default"]
        _write(conn, key, None, None, None)
        enqueue(conn, "settings.changed", {"key": key, "old": before["value"],
                                           "new": before["default"], "reset": True,
                                           "operator_id": operator_id}, at=now)
    return before["default"]
