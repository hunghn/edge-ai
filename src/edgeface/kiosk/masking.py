# -*- coding: utf-8 -*-
"""Hiding one patient's identity while another patient is being dealt with.

When the kiosk warns that a face is already enrolled, it is showing a nurse information
about somebody who is not standing in front of them and has not consented to appear on
that screen. The face is shown, because it is the only thing that answers "is this the
same person"; the name is not, because it answers nothing the nurse needs.

Pure functions, no Qt, no database — every rule here is a test case.
"""

MASK = "***"
KEEP_HEAD = 2
KEEP_TAIL = 2


def mask_code(code):
    """'BN000201' -> 'BN****01'.

    Enough for an administrator to find the record later, not enough to read off the
    screen and look somebody up. Short codes reveal proportionally less rather than
    more: keeping two characters of a four-character code would expose half of it, so
    the kept portion is capped at half the length.
    """
    if not code:
        return MASK
    code = str(code)
    budget = len(code) // 2
    if budget <= 0:
        return MASK
    head = min(KEEP_HEAD, budget)
    tail = min(KEEP_TAIL, budget - head)
    hidden = len(code) - head - tail
    if hidden <= 0:
        return MASK
    return code[:head] + "*" * hidden + (code[len(code) - tail:] if tail else "")


def mask_name(name):
    """Names are hidden outright: no initials, no length, nothing to recognise by."""
    return MASK
