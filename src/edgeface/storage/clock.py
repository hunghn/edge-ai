"""Wall-clock time as epoch seconds (UTC), replaceable in tests.

Python 3.6 has no datetime.fromisoformat, and TTLs must survive process restarts, so
every timestamp in the database is a REAL epoch value. Format only when displaying.
"""
import time

_now_fn = time.time


def now():
    return _now_fn()


def set_clock(fn):
    """Test helper: install a fake clock. Returns the previous one."""
    global _now_fn
    previous = _now_fn
    _now_fn = fn
    return previous


def reset_clock():
    global _now_fn
    _now_fn = time.time


def format_ts(ts):
    """Epoch -> 'YYYY-MM-DD HH:MM:SS' in local time (display only)."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def local_date(ts):
    """Epoch -> 'YYYY-MM-DD' in local time; used for appointment dates."""
    return time.strftime("%Y-%m-%d", time.localtime(ts))
