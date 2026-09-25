# -*- coding: utf-8 -*-
"""On-screen keyboard: the kiosk is a touchscreen with no keys.

Unaccented only. patients.search() matches on `name_search`, which has already had its
accents stripped, and a patient code is ASCII, so nothing here needs tones yet. A Telex
layout waits on D-25 together with the screen size.
"""
from PyQt5 import QtCore, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons

LETTERS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
DIGITS = ("1234567890", "-./:", "")


class SoftKeyboard(QtWidgets.QWidget):
    """Types into whichever attached QLineEdit last had focus."""

    text_typed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super(SoftKeyboard, self).__init__(parent)
        self.setObjectName("keyboard")
        self._numeric = False
        self._target = None
        self._keys = []
        self.grid = QtWidgets.QVBoxLayout(self)
        self.grid.setContentsMargins(12, 10, 12, 10)
        self.grid.setSpacing(7)
        self._rows = [self._row() for _ in range(3)]
        self._build()

    def _row(self):
        box = QtWidgets.QHBoxLayout()
        box.setSpacing(7)
        self.grid.addLayout(box)
        return box

    def _key(self, text, handler, stretch=1, icon_name=None):
        button = QtWidgets.QPushButton("" if icon_name else text)
        button.setObjectName("kbKey")
        button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        if icon_name:
            button.setIcon(icons.icon(icon_name, 22, theme.colour("on_surface_var")))
            button.setIconSize(QtCore.QSize(22, 22))
        button.clicked.connect(handler)
        self._keys.append(button)
        return button, stretch

    def _build(self):
        """Lay the keys out once; switching layouts only relabels them."""
        rows = DIGITS if self._numeric else LETTERS
        for box in self._rows:
            while box.count():
                item = box.takeAt(0)
                if item.widget() is not None:
                    item.widget().deleteLater()
        self._keys = []

        for index, row in enumerate(rows):
            box = self._rows[index]
            if index == 2:
                button, stretch = self._key(u"123" if not self._numeric else u"ABC",
                                            self._toggle, 2)
                box.addWidget(button, stretch)
            for character in row:
                button, stretch = self._key(character,
                                            lambda _c=False, ch=character: self.type(ch))
                box.addWidget(button, stretch)
            if index == 1:
                button, stretch = self._key("", self.backspace, 2,
                                            icon_name="backspace")
                box.addWidget(button, stretch)
            if index == 2:
                button, stretch = self._key(u"dấu cách", lambda _c=False: self.type(" "), 4)
                box.addWidget(button, stretch)

    def _toggle(self):
        self._numeric = not self._numeric
        self._build()

    # ------------------------------------------------------------------ typing
    def attach(self, *line_edits):
        """Follow the focus across a form's fields; the first one is the default."""
        for line_edit in line_edits:
            line_edit.installEventFilter(self)
        if line_edits and self._target is None:
            self._target = line_edits[0]

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.FocusIn:
            self._target = obj
        return False

    def set_target(self, line_edit):
        self._target = line_edit

    def type(self, character):
        if self._target is not None:
            self._target.insert(character)
        self.text_typed.emit(character)

    def backspace(self):
        if self._target is not None:
            self._target.backspace()
        self.text_typed.emit("")
