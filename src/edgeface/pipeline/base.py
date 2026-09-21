"""Helpers so every stage returns the same shape."""
from edgeface.types import StageResult


def ok(data=None):
    return StageResult(True, None, data)


def fail(reason, data=None):
    return StageResult(False, reason, data)
