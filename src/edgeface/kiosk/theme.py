# -*- coding: utf-8 -*-
"""One source of truth for the kiosk's colours and sizes.

style.qss is written with @token placeholders and gets them substituted from PALETTE at
load time, so a colour is written down once and the widgets that paint themselves
(icons, the countdown ring, the patient rows) read the same value the stylesheet does.

Material 3 light scheme, seeded teal: the kiosk stands in a bright clinic room, and only
the camera panel keeps a dark ground. The three status colours mean what they meant in
the first version — green passed, amber needs a hand, red stop.
"""

PALETTE = {
    "primary": "#00696B",
    "on_primary": "#FFFFFF",
    "primary_container": "#9DF2EF",
    "on_primary_container": "#00201F",

    "surface": "#F3FAF9",
    "surface_1": "#E9F3F2",
    "surface_2": "#DFEBE9",
    "surface_3": "#D2E1DF",
    "on_surface": "#0D1B19",
    "on_surface_var": "#3E4A48",

    "outline": "#6E7A78",
    "outline_var": "#BCC8C6",

    "ok": "#186B3E",
    "ok_container": "#A8F2C3",
    "on_ok_container": "#00210E",
    "warn": "#7A4E00",
    "warn_container": "#FFDDB0",
    "on_warn_container": "#291800",
    "error": "#B3261E",
    "error_container": "#FFDAD5",
    "on_error_container": "#410E0B",

    "camera": "#0B1312",
    "camera_edge": "#9DF2EF",
    "scrim": "rgba(10, 22, 20, 128)",
}

# Touch sizes, in pixels at the 1024x600 the kiosk is laid out for (D-25 still open).
BUTTON_H = 64
BUTTON_PRIMARY_H = 84
KEY_H = 78
ROW_H = 76
RADIUS = 26
GUTTER = 30

# Severity -> the container/on-container pair a banner or chip paints itself with.
TONES = {
    "ok": ("ok_container", "on_ok_container", "ok"),
    "attention": ("warn_container", "on_warn_container", "warn"),
    "alarm": ("error_container", "on_error_container", "error"),
    "primary": ("primary_container", "on_primary_container", "primary"),
    "neutral": ("surface_2", "on_surface_var", "outline"),
}


def colour(name):
    """A palette entry as a hex string. Unknown names raise, so typos surface at once."""
    return PALETTE[name]


def qcolor(name):
    from PyQt5 import QtGui

    return QtGui.QColor(PALETTE[name])


def tone_colours(tone):
    """(background, foreground, accent) for one of TONES."""
    background, foreground, accent = TONES.get(tone, TONES["neutral"])
    return PALETTE[background], PALETTE[foreground], PALETTE[accent]


def apply_tokens(qss):
    """Replace every @token in the stylesheet with its palette value.

    Longest name first: @on_primary_container must not be eaten by @on_primary.
    """
    for name in sorted(PALETTE, key=len, reverse=True):
        qss = qss.replace("@" + name, PALETTE[name])
    return qss
