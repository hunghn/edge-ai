# -*- coding: utf-8 -*-
"""Progress through the pipeline, for the two screens where waiting has to make sense.

VStepper is the five pipeline gates on the guidance screen: standing still in front of a
screen that says nothing for four seconds feels like a hung machine, and the stepper is
what turns that silence into progress.

HStepper is the three steps of enrolment, where the nurse needs to know how much is left
before the patient can sit down again.
"""
from PyQt5 import QtCore, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons

DONE = "done"
NOW = "now"
TODO = "todo"


class _Dot(QtWidgets.QLabel):
    def __init__(self, size=30, parent=None):
        super(_Dot, self).__init__(parent)
        self._state = None
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.set_state(TODO)

    def set_state(self, state):
        if state == self._state:
            return
        self._state = state
        from PyQt5 import QtGui

        image = QtGui.QPixmap(self._size, self._size)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        middle = self._size / 2.0
        radius = middle - 2.0
        if state == DONE:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(theme.qcolor("ok")))
            painter.drawEllipse(QtCore.QPointF(middle, middle), radius, radius)
            painter.end()
            painter = QtGui.QPainter(image)
            painter.translate((self._size - 16) / 2.0, (self._size - 16) / 2.0)
            icons.paint(painter, "check", 16, theme.colour("on_primary"), 2.4)
        else:
            colour = theme.colour("primary") if state == NOW else theme.colour("outline_var")
            pen = QtGui.QPen(QtGui.QColor(colour))
            pen.setWidthF(3.4 if state == NOW else 2.4)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(QtCore.QPointF(middle, middle), radius, radius)
        painter.end()
        self.setPixmap(image)


class VStepper(QtWidgets.QWidget):
    """One row per gate. `render(states)` takes a list of DONE / NOW / TODO."""

    def __init__(self, labels, parent=None):
        super(VStepper, self).__init__(parent)
        self._states = None
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self.dots = []
        self.labels = []
        for text in labels:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(16)
            dot = _Dot()
            label = QtWidgets.QLabel(text)
            label.setObjectName("stepTodo")
            row.addWidget(dot)
            row.addWidget(label, 1)
            box.addLayout(row)
            self.dots.append(dot)
            self.labels.append(label)

    def render(self, states):
        states = tuple(states)
        if states == self._states:
            return
        self._states = states
        for index, dot in enumerate(self.dots):
            state = states[index] if index < len(states) else TODO
            dot.set_state(state)
            label = self.labels[index]
            name = {DONE: "stepDone", NOW: "stepNow"}.get(state, "stepTodo")
            if label.objectName() != name:
                label.setObjectName(name)
                label.style().unpolish(label)
                label.style().polish(label)


class HStepper(QtWidgets.QWidget):
    """Numbered steps in a row, with a rule between them."""

    def __init__(self, labels, parent=None):
        super(HStepper, self).__init__(parent)
        self._active = None
        box = QtWidgets.QHBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(14)
        self.numbers = []
        self.labels = []
        for index, text in enumerate(labels):
            if index:
                rule = QtWidgets.QFrame()
                rule.setObjectName("stepRule")
                rule.setFixedHeight(2)
                rule.setFrameShape(QtWidgets.QFrame.HLine)
                box.addWidget(rule, 1)
            number = QtWidgets.QLabel(str(index + 1))
            number.setObjectName("stepNumberTodo")
            number.setFixedSize(38, 38)
            number.setAlignment(QtCore.Qt.AlignCenter)
            label = QtWidgets.QLabel(text)
            label.setObjectName("stepTodo")
            box.addWidget(number)
            box.addWidget(label)
            self.numbers.append(number)
            self.labels.append(label)

    def render(self, active):
        """`active` is the zero-based index of the step being worked on."""
        if active == self._active:
            return
        self._active = active
        for index in range(len(self.numbers)):
            state = DONE if index < active else (NOW if index == active else TODO)
            number = self.numbers[index]
            name = {DONE: "stepNumberDone", NOW: "stepNumberNow"}.get(
                state, "stepNumberTodo")
            if number.objectName() != name:
                number.setObjectName(name)
                number.style().unpolish(number)
                number.style().polish(number)
            number.setText(u"✓" if state == DONE else str(index + 1))
            label = self.labels[index]
            label_name = {DONE: "stepDone", NOW: "stepNow"}.get(state, "stepTodo")
            if label.objectName() != label_name:
                label.setObjectName(label_name)
                label.style().unpolish(label)
                label.style().polish(label)
