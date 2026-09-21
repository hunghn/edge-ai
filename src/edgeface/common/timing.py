"""Per-stage latency recording. time.monotonic() based, in-process."""
import functools
import threading
import time
from collections import defaultdict, deque

import numpy as np


def now():
    return time.monotonic()


class LatencyRecorder(object):
    """Keeps the last `maxlen` samples (milliseconds) per stage."""

    def __init__(self, maxlen=10000):
        self._lock = threading.Lock()
        self._samples = defaultdict(lambda: deque(maxlen=maxlen))

    def add(self, stage, ms):
        with self._lock:
            self._samples[stage].append(float(ms))

    def summary(self):
        """{stage: {"n", "mean", "p50", "p95", "max"}} in ms."""
        with self._lock:
            items = [(k, np.asarray(v, dtype=np.float64)) for k, v in self._samples.items()]
        out = {}
        for stage, arr in items:
            if arr.size == 0:
                continue
            out[stage] = {
                "n": int(arr.size),
                "mean": float(arr.mean()),
                "p50": float(np.percentile(arr, 50)),
                "p95": float(np.percentile(arr, 95)),
                "max": float(arr.max()),
            }
        return out

    def reset(self):
        with self._lock:
            self._samples.clear()


RECORDER = LatencyRecorder()


def timed(stage, recorder=None):
    """Decorator: record wall-clock latency of each call under `stage`."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = now()
            try:
                return fn(*args, **kwargs)
            finally:
                (recorder or RECORDER).add(stage, (now() - t0) * 1000.0)

        return wrapper

    return decorator
