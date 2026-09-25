# -*- coding: utf-8 -*-
"""An in-page confirmation, for the one action that cannot be undone.

Revoking a patient deletes their face data from this machine. The first version turned
the message banner into a question and put the Revoke button right beside the row that
had just been tapped, so two taps in the same corner of the screen destroyed a record.

A child widget rather than QDialog: a modal dialog spins its own event loop, which stops
the state polling behind it and hangs an offscreen test.
"""
from PyQt5 import QtCore, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons


class ConfirmDialog(QtWidgets.QWidget):
    confirmed = QtCore.pyqtSignal()
    cancelled = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super(ConfirmDialog, self).__init__(parent)
        self.setObjectName("scrim")
        self.setAutoFillBackground(True)
        self.hide()

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        middle = QtWidgets.QHBoxLayout()
        middle.addStretch(1)
        self.panel = QtWidgets.QFrame()
        self.panel.setObjectName("dialog")
        self.panel.setMinimumWidth(560)
        self.panel.setMaximumWidth(680)
        middle.addWidget(self.panel)
        middle.addStretch(1)
        outer.addLayout(middle)
        outer.addStretch(1)

        box = QtWidgets.QVBoxLayout(self.panel)
        box.setContentsMargins(30, 28, 30, 26)
        box.setSpacing(16)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(44, 44)
        box.addWidget(self.icon)
        self.title = QtWidgets.QLabel("")
        self.title.setObjectName("headline")
        self.title.setWordWrap(True)
        box.addWidget(self.title)
        self.body = QtWidgets.QLabel("")
        self.body.setObjectName("body")
        self.body.setWordWrap(True)
        box.addWidget(self.body)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(14)
        buttons.addStretch(1)
        self.cancel_button = QtWidgets.QPushButton("")
        self.cancel_button.setObjectName("text")
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)
        self.confirm_button = QtWidgets.QPushButton("")
        self.confirm_button.setObjectName("dangerFilled")
        self.confirm_button.clicked.connect(self._confirm)
        buttons.addWidget(self.confirm_button)
        box.addLayout(buttons)

    def ask(self, title, body, confirm_label, cancel_label, icon_name="trash",
            tone="alarm"):
        self.title.setText(title)
        self.body.setText(body)
        self.confirm_button.setText(confirm_label)
        self.cancel_button.setText(cancel_label)
        _background, _foreground, accent = theme.tone_colours(tone)
        self.icon.setPixmap(icons.pixmap(icon_name, 44, accent, 2.4))
        self.confirm_button.setObjectName(
            "dangerFilled" if tone == "alarm" else "primary")
        self.confirm_button.style().unpolish(self.confirm_button)
        self.confirm_button.style().polish(self.confirm_button)
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()

    def follow(self):
        """Keep covering the page after a resize. Called from the page's resizeEvent."""
        if self.isVisible() and self.parent() is not None:
            self.setGeometry(self.parent().rect())

    def _confirm(self):
        self.hide()
        self.confirmed.emit()

    def _cancel(self):
        self.hide()
        self.cancelled.emit()
