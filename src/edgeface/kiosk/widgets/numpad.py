# -*- coding: utf-8 -*-
"""On-screen number pad: the kiosk has no keyboard (PIN, birth year)."""
from PyQt5 import QtCore, QtWidgets


class NumPad(QtWidgets.QWidget):
    digit_pressed = QtCore.pyqtSignal(str)
    backspace_pressed = QtCore.pyqtSignal()
    accepted = QtCore.pyqtSignal()

    def __init__(self, parent=None, accept_label="OK"):
        super(NumPad, self).__init__(parent)
        grid = QtWidgets.QGridLayout(self)
        grid.setSpacing(10)
        for index, digit in enumerate("123456789"):
            grid.addWidget(self._key(digit), index // 3, index % 3)
        back = QtWidgets.QPushButton("⌫")
        back.setObjectName("keypad")
        back.clicked.connect(self.backspace_pressed.emit)
        grid.addWidget(back, 3, 0)
        grid.addWidget(self._key("0"), 3, 1)
        accept = QtWidgets.QPushButton(accept_label)
        accept.setObjectName("primary")
        accept.clicked.connect(self.accepted.emit)
        grid.addWidget(accept, 3, 2)

    def _key(self, digit):
        button = QtWidgets.QPushButton(digit)
        button.setObjectName("keypad")
        button.clicked.connect(lambda _checked=False, d=digit: self.digit_pressed.emit(d))
        return button
