# -*- coding: utf-8 -*-
"""The AWAIT_NURSE countdown, as a ring beside the button it applies to.

The first version put "Tự huỷ sau 29 giây" in small grey type in a corner, far from the
Confirm button it was about. A ring next to the button says the same thing where the
nurse is already looking.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.kiosk import theme


class CountdownRing(QtWidgets.QWidget):
    def __init__(self, size=72, parent=None):
        super(CountdownRing, self).__init__(parent)
        self.setFixedSize(size, size)
        self._fraction = 1.0
        self._seconds = None
        self.label = QtWidgets.QLabel("", self)
        self.label.setObjectName("mono")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setGeometry(0, 0, size, size)
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

    def render(self, remaining_s, total_s):
        """Hide the ring when there is no deadline to show."""
        if remaining_s is None or not total_s:
            self.setVisible(False)
            return
        self.setVisible(True)
        seconds = int(remaining_s)
        fraction = max(0.0, min(1.0, float(remaining_s) / float(total_s)))
        # Repaint on whole seconds only: this runs ten times a second.
        if seconds == self._seconds:
            return
        self._seconds = seconds
        self._fraction = fraction
        self.label.setText(str(seconds))
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        width = 5.0
        box = QtCore.QRectF(width, width, self.width() - 2 * width,
                            self.height() - 2 * width)
        pen = QtGui.QPen(theme.qcolor("surface_3"))
        pen.setWidthF(width)
        painter.setPen(pen)
        painter.drawEllipse(box)
        # Under a fifth left is when the nurse should know the session is about to close.
        pen.setColor(theme.qcolor("warn" if self._fraction < 0.2 else "primary"))
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(box, 90 * 16, -int(round(360 * 16 * self._fraction)))
        painter.end()
