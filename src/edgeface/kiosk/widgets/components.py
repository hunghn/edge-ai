# -*- coding: utf-8 -*-
"""The small Material pieces the pages are assembled from.

Every widget here can be updated in place. Nothing on a kiosk page may be rebuilt on a
redraw: render() runs ten times a second, and replacing a widget between a finger going
down and coming up loses the tap.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons


class Chip(QtWidgets.QFrame):
    """A small labelled pill, optionally with an icon and a status colour."""

    def __init__(self, text="", icon_name=None, tone="neutral", parent=None):
        super(Chip, self).__init__(parent)
        self.setObjectName("chip")
        self._tone = None
        self._icon_name = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(14, 7, 14, 7)
        row.setSpacing(8)
        self.icon = QtWidgets.QLabel()
        self.icon.setVisible(False)
        row.addWidget(self.icon)
        self.label = QtWidgets.QLabel(text)
        self.label.setObjectName("chipText")
        row.addWidget(self.label)
        self.set_tone(tone)
        self.set_icon(icon_name)

    def set_text(self, text):
        if self.label.text() != text:
            self.label.setText(text)

    def set_tone(self, tone):
        if tone == self._tone:
            return
        self._tone = tone
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._icon_name:                     # the glyph follows the text colour
            self._paint_icon()

    def set_icon(self, name, size=22):
        if name == self._icon_name:
            return
        self._icon_name = name
        self._icon_size = size
        self._paint_icon()

    def _paint_icon(self):
        if not self._icon_name:
            self.icon.setVisible(False)
            return
        _background, foreground, _accent = theme.tone_colours(self._tone)
        size = getattr(self, "_icon_size", 22)
        self.icon.setPixmap(icons.pixmap(self._icon_name, size, foreground))
        self.icon.setFixedSize(size, size)
        self.icon.setVisible(True)


class Card(QtWidgets.QFrame):
    """A surface that groups related rows. `outlined` for the secondary, quieter one."""

    def __init__(self, outlined=False, parent=None):
        super(Card, self).__init__(parent)
        self.setObjectName("cardOutlined" if outlined else "card")
        self.body = QtWidgets.QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 22)
        self.body.setSpacing(14)

    def add(self, widget, stretch=0):
        self.body.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout):
        self.body.addLayout(layout)
        return layout


class SectionLabel(QtWidgets.QLabel):
    def __init__(self, text="", parent=None):
        super(SectionLabel, self).__init__(text.upper(), parent)
        self.setObjectName("sectionLabel")


class Banner(QtWidgets.QFrame):
    """The one sentence that says what is happening, coloured by severity."""

    ICONS = {"ok": "check_circle", "attention": "warning", "alarm": "error"}

    def __init__(self, parent=None):
        super(Banner, self).__init__(parent)
        self.setObjectName("banner")
        self._severity = None
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(20, 18, 20, 18)
        row.setSpacing(16)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(32, 32)
        self.icon.setAlignment(QtCore.Qt.AlignTop)
        row.addWidget(self.icon, 0, QtCore.Qt.AlignTop)
        self.label = QtWidgets.QLabel("")
        self.label.setObjectName("bannerText")
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)

    def render(self, text, severity):
        if self.label.text() != text:
            self.label.setText(text)
        if severity != self._severity:
            self._severity = severity
            self.setProperty("severity", severity)
            self.style().unpolish(self)
            self.style().polish(self)
            _background, foreground, _accent = theme.tone_colours(severity)
            self.icon.setPixmap(icons.pixmap(self.ICONS.get(severity, "info"), 32,
                                             foreground, 2.2))
        self.setVisible(bool(text))


class Avatar(QtWidgets.QLabel):
    """Initials in a circle. The gallery holds no portraits, so initials are what we have."""

    def __init__(self, text="", primary=False, size=56, parent=None):
        super(Avatar, self).__init__(parent)
        self.setObjectName("avatarPrimary" if primary else "avatar")
        self.setFixedSize(size, size)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_name(text)

    def set_name(self, full_name):
        initials = "".join(part[0] for part in (full_name or "").split()[-2:]).upper()
        if self.text() != initials:
            self.setText(initials)


class IconButton(QtWidgets.QPushButton):
    def __init__(self, icon_name, colour=None, size=28, parent=None):
        super(IconButton, self).__init__(parent)
        self.setObjectName("iconOnly")
        self.setIcon(icons.icon(icon_name, size, colour or theme.colour("on_surface_var")))
        self.setIconSize(QtCore.QSize(size, size))
        self.setFlat(True)


class StatusDot(QtWidgets.QLabel):
    def __init__(self, tone="ok", size=16, parent=None):
        super(StatusDot, self).__init__(parent)
        self._tone = None
        self._size = size
        self.setFixedSize(size, size)
        self.set_tone(tone)

    def set_tone(self, tone):
        if tone == self._tone:
            return
        self._tone = tone
        _background, _foreground, accent = theme.tone_colours(tone)
        image = QtGui.QPixmap(self._size, self._size)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(accent)))
        painter.drawEllipse(0, 0, self._size, self._size)
        painter.end()
        self.setPixmap(image)


class MetricTile(QtWidgets.QFrame):
    """One number on the status screen, with the word that makes it readable."""

    def __init__(self, label="", parent=None):
        super(MetricTile, self).__init__(parent)
        self.setObjectName("tile")
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(20, 17, 20, 17)
        box.setSpacing(4)
        self.label = QtWidgets.QLabel(label.upper())
        self.label.setObjectName("tileLabel")
        box.addWidget(self.label)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.dot = StatusDot("ok")
        self.dot.setVisible(False)
        row.addWidget(self.dot)
        self.value = QtWidgets.QLabel("")
        self.value.setObjectName("tileValue")
        row.addWidget(self.value)
        row.addStretch(1)
        box.addLayout(row)
        self.foot = QtWidgets.QLabel("")
        self.foot.setObjectName("tileFoot")
        self.foot.setWordWrap(True)
        box.addWidget(self.foot)

    def render(self, label, value, foot="", tone=None):
        if self.label.text() != label.upper():
            self.label.setText(label.upper())
        if self.value.text() != value:
            self.value.setText(value)
        if self.foot.text() != foot:
            self.foot.setText(foot)
        self.dot.setVisible(tone is not None)
        if tone is not None:
            self.dot.set_tone(tone)


def row(*widgets, **kwargs):
    """A horizontal layout, because four lines of boilerplate per row adds up."""
    spacing = kwargs.pop("spacing", 12)
    box = QtWidgets.QHBoxLayout()
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            box.addStretch(1)
        elif isinstance(widget, QtWidgets.QLayout):
            box.addLayout(widget)
        else:
            box.addWidget(widget)
    return box


def label(text="", name="body", wrap=False):
    widget = QtWidgets.QLabel(text)
    widget.setObjectName(name)
    if wrap:
        widget.setWordWrap(True)
    return widget
