# -*- coding: utf-8 -*-
"""Line icons drawn with QPainter.

The Nano has no icon font and this repository ships no image assets, so every glyph is a
handful of strokes on a 24x24 grid, drawn at whatever size and colour the caller asks
for. QtSvg is not guaranteed to be installed with the apt PyQt5, which rules out SVG.

Each icon is a list of primitives:
    ("line", x1, y1, x2, y2)
    ("poly", [(x, y), ...])          open polyline
    ("shape", [(x, y), ...])         closed polygon, stroked
    ("circle", cx, cy, r)            stroked
    ("dot", cx, cy, r)               filled
    ("rect", x, y, w, h, radius)     stroked, rounded
    ("arc", x, y, w, h, start, span) degrees, counter-clockwise like Qt
"""
from PyQt5 import QtCore, QtGui

from edgeface.kiosk import theme

GRID = 24.0
_CACHE = {}

_S = 0.70710678                       # the diagonal of a unit circle, for ray icons
_RAYS = [("line", 12 + 7 * dx, 12 + 7 * dy, 12 + 9.5 * dx, 12 + 9.5 * dy)
         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                        (_S, _S), (-_S, _S), (_S, -_S), (-_S, -_S))]

ICONS = {
    "check": [("poly", [(5, 12.5), (10, 17.5), (19, 6.5)])],
    "check_circle": [("circle", 12, 12, 9), ("poly", [(7.5, 12), (11, 15.5), (16.5, 8)])],
    "close": [("line", 6, 6, 18, 18), ("line", 18, 6, 6, 18)],
    "back": [("line", 4.5, 12, 20, 12), ("poly", [(11, 5), (4, 12), (11, 19)])],
    "chevron": [("poly", [(10, 5.5), (16.5, 12), (10, 18.5)])],
    "refresh": [("arc", 4, 4, 16, 16, 60, 280),
                ("poly", [(14.5, 4.5), (20, 5.5), (19, 11)])],
    "search": [("circle", 10, 10, 6), ("line", 14.4, 14.4, 20, 20)],
    "zoom": [("circle", 10, 10, 6), ("line", 14.4, 14.4, 20, 20),
             ("line", 7, 10, 13, 10), ("line", 10, 7, 10, 13)],
    "person": [("circle", 12, 8, 4), ("arc", 4.5, 13, 15, 15, 0, 180)],
    "person_add": [("circle", 9, 8, 3.6), ("arc", 2, 13, 14, 14, 0, 180),
                   ("line", 18.5, 4.5, 18.5, 11), ("line", 15.2, 7.8, 21.8, 7.8)],
    "group": [("circle", 9, 8, 3.4), ("arc", 2.5, 12.5, 13, 13, 0, 180),
              ("circle", 17.5, 7.5, 2.6), ("arc", 13.5, 12, 10, 10, 0, 130)],
    "no_person": [("circle", 12, 8, 4), ("arc", 4.5, 13, 15, 15, 0, 180),
                  ("line", 4, 20, 20, 4)],
    "lock": [("rect", 5, 10.5, 14, 9.5, 2.5), ("arc", 8, 4.5, 8, 10, 0, 180)],
    "key": [("circle", 7.5, 12, 4), ("line", 11.5, 12, 20, 12),
            ("line", 17, 12, 17, 16), ("line", 20, 12, 20, 15.5)],
    "logout": [("poly", [(10, 4.5), (4, 4.5), (4, 19.5), (10, 19.5)]),
               ("line", 8.5, 12, 20, 12), ("poly", [(16, 8), (20, 12), (16, 16)])],
    "camera": [("rect", 3, 7, 18, 12.5, 3.5), ("circle", 12, 13.2, 3.8),
               ("poly", [(8, 7), (9.8, 4.2), (14.2, 4.2), (16, 7)])],
    "photo": [("rect", 3, 5, 18, 14, 3.5), ("dot", 8, 9.5, 1.5),
              ("poly", [(4.5, 17), (10.5, 11), (14, 14.5), (17, 11.8), (20, 15)])],
    "eye": [("arc", 2, 2.5, 20, 19, 25, 130), ("arc", 2, 2.5, 20, 19, 205, 130),
            ("circle", 12, 12, 3)],
    "clock": [("circle", 12, 12, 9), ("poly", [(12, 6.8), (12, 12.4), (16, 14.4)])],
    "warning": [("shape", [(12, 3.5), (21, 19.5), (3, 19.5)]),
                ("line", 12, 9.5, 12, 14), ("dot", 12, 16.8, 1.1)],
    "error": [("circle", 12, 12, 9), ("line", 12, 6.8, 12, 13),
              ("dot", 12, 16.2, 1.1)],
    "info": [("circle", 12, 12, 9), ("line", 12, 11, 12, 17.2),
             ("dot", 12, 7.6, 1.1)],
    "shield": [("shape", [(12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6)])],
    "shield_check": [("shape", [(12, 3), (20, 6), (20, 12), (12, 21), (4, 12), (4, 6)]),
                     ("poly", [(8.2, 11.4), (11, 14.2), (15.8, 8.6)])],
    "trash": [("line", 3.5, 6.8, 20.5, 6.8), ("rect", 6, 6.8, 12, 13.2, 2.5),
              ("line", 9.5, 4.2, 14.5, 4.2), ("line", 10, 10.5, 10, 16.5),
              ("line", 14, 10.5, 14, 16.5)],
    "sync": [("arc", 4, 4, 16, 16, 40, 140), ("arc", 4, 4, 16, 16, 220, 140),
             ("poly", [(3.5, 8.5), (4.5, 3.5), (9, 5.5)]),
             ("poly", [(20.5, 15.5), (19.5, 20.5), (15, 18.5)])],
    "pulse": [("poly", [(3, 12), (7.5, 12), (10, 5.5), (13.5, 18.5), (16, 12), (21, 12)])],
    "calendar": [("rect", 3, 5, 18, 16, 3.5), ("line", 3, 10, 21, 10),
                 ("line", 8, 3, 8, 7), ("line", 16, 3, 16, 7)],
    "sun": [("circle", 12, 12, 4.4)] + _RAYS,
    "bulb": [("circle", 12, 9, 5), ("line", 9.5, 15.5, 14.5, 15.5),
             ("line", 10, 18.5, 14, 18.5)],
    "backspace": [("shape", [(8, 4.5), (21, 4.5), (21, 19.5), (8, 19.5), (2.5, 12)]),
                  ("line", 11, 9, 17, 15), ("line", 17, 9, 11, 15)],
    "keyboard": [("rect", 2, 6, 20, 13, 3), ("dot", 6.5, 10.5, 1), ("dot", 12, 10.5, 1),
                 ("dot", 17.5, 10.5, 1), ("line", 7, 15, 17, 15)],
    "cloud": [("circle", 8.5, 13, 4), ("circle", 14.5, 11.5, 5),
              ("line", 7.5, 17, 16.5, 17)],
    "wifi": [("arc", 2, 5, 20, 20, 35, 110), ("arc", 5.5, 8.5, 13, 13, 35, 110),
             ("dot", 12, 18, 1.4)],
    "signal_off": [("arc", 2, 5, 20, 20, 35, 110), ("arc", 5.5, 8.5, 13, 13, 35, 110),
                   ("dot", 12, 18, 1.4), ("line", 4, 20, 20, 4)],
    "folder": [("shape", [(3, 6.5), (9, 6.5), (11, 9.5), (21, 9.5), (21, 19.5),
                          (3, 19.5)])],
    "tune": [("line", 3, 8, 21, 8), ("line", 3, 16, 21, 16), ("dot", 9, 8, 2.6),
             ("dot", 15, 16, 2.6)],
    "save": [("rect", 4, 4, 16, 16, 2.5), ("rect", 8.5, 4, 7, 5.5, 1),
             ("rect", 7, 13, 10, 7, 1)],
    "pause": [("rect", 8, 5, 3, 14, 1.2), ("rect", 13, 5, 3, 14, 1.2)],
    "hospital": [("rect", 4, 4, 16, 16, 4.5), ("line", 12, 8, 12, 16),
                 ("line", 8, 12, 16, 12)],
    "face": [("circle", 12, 12, 9), ("dot", 9, 10, 1.2), ("dot", 15, 10, 1.2),
             ("arc", 7.5, 8, 9, 9, 200, 140)],
    "blur": [("dot", 7, 7, 1.7), ("dot", 12, 6, 1.1), ("dot", 17, 7, 1.7),
             ("dot", 6, 12, 1.1), ("dot", 12, 12, 2.2), ("dot", 18, 12, 1.1),
             ("dot", 7, 17, 1.7), ("dot", 12, 18, 1.1), ("dot", 17, 17, 1.7)],
    "badge": [("rect", 4, 6.5, 16, 13.5, 3), ("line", 9, 3.5, 15, 3.5),
              ("line", 8.5, 11, 15.5, 11), ("line", 8.5, 15, 15.5, 15)],
    "checklist": [("line", 10.5, 6.5, 20.5, 6.5), ("line", 10.5, 12, 20.5, 12),
                  ("line", 10.5, 17.5, 20.5, 17.5),
                  ("poly", [(3, 6.5), (4.8, 8.3), (8, 4.5)]),
                  ("poly", [(3, 12), (4.8, 13.8), (8, 10)])],
    "ruler": [("rect", 2, 9, 20, 6, 2), ("line", 7, 9, 7, 12), ("line", 12, 9, 12, 12),
              ("line", 17, 9, 17, 12)],
    "dots": [("dot", 6, 12, 2), ("dot", 12, 12, 2), ("dot", 18, 12, 2)],
    "plus": [("line", 12, 5, 12, 19), ("line", 5, 12, 19, 12)],
    "minus": [("line", 5, 12, 19, 12)],
}

# Names the pages use that are the same drawing as another icon.
ALIAS = {"timer": "clock", "verified": "shield_check", "password": "key",
         "delete": "trash", "manage_search": "search", "monitor": "pulse",
         "fact_check": "checklist", "retry": "refresh", "ok": "check_circle"}


def _pen(painter, colour, width):
    pen = QtGui.QPen(QtGui.QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)


def paint(painter, name, size, colour, width=2.0):
    """Draw one icon into an existing painter, at the painter's current origin."""
    primitives = ICONS.get(ALIAS.get(name, name))
    if primitives is None:
        return False
    scale = float(size) / GRID
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.scale(scale, scale)
    _pen(painter, colour, width / scale)
    for item in primitives:
        kind = item[0]
        if kind == "line":
            painter.drawLine(QtCore.QLineF(item[1], item[2], item[3], item[4]))
        elif kind in ("poly", "shape"):
            points = [QtCore.QPointF(x, y) for x, y in item[1]]
            if kind == "shape":
                painter.drawPolygon(QtGui.QPolygonF(points))
            else:
                painter.drawPolyline(QtGui.QPolygonF(points))
        elif kind == "circle":
            painter.drawEllipse(QtCore.QPointF(item[1], item[2]), item[3], item[3])
        elif kind == "dot":
            painter.setBrush(QtGui.QBrush(QtGui.QColor(colour)))
            painter.drawEllipse(QtCore.QPointF(item[1], item[2]), item[3], item[3])
            painter.setBrush(QtCore.Qt.NoBrush)
        elif kind == "rect":
            painter.drawRoundedRect(QtCore.QRectF(item[1], item[2], item[3], item[4]),
                                    item[5], item[5])
        elif kind == "arc":
            # Qt counts sixteenths of a degree, and measures from three o'clock.
            painter.drawArc(QtCore.QRectF(item[1], item[2], item[3], item[4]),
                            int(item[5] * 16), int(item[6] * 16))
    painter.restore()
    return True


def pixmap(name, size=24, colour=None, width=2.0):
    """One icon as a transparent pixmap. Cached: the same glyph is drawn many times."""
    colour = colour or theme.colour("on_surface_var")
    key = (ALIAS.get(name, name), int(size), colour, width)
    if key in _CACHE:
        return _CACHE[key]
    image = QtGui.QPixmap(int(size), int(size))
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    drawn = paint(painter, name, size, colour, width)
    painter.end()
    if not drawn:
        # An unknown name is a typo in a page, not a reason to crash the kiosk in front
        # of a patient; an empty square is visible enough in a screenshot review.
        image.fill(QtCore.Qt.transparent)
    _CACHE[key] = image
    return image


def icon(name, size=24, colour=None, width=2.0):
    return QtGui.QIcon(pixmap(name, size, colour, width))


def label(name, size=24, colour=None, width=2.0, parent=None):
    """An icon as a QLabel, for rows that mix glyphs and text in a layout."""
    from PyQt5 import QtWidgets

    widget = QtWidgets.QLabel(parent)
    widget.setPixmap(pixmap(name, size, colour, width))
    widget.setFixedSize(int(size), int(size))
    return widget
