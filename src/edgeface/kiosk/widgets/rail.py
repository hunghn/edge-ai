# -*- coding: utf-8 -*-
"""The admin navigation rail.

The first version gave the admin screen a column of buttons, so every job ended by
walking back to the menu before the next one could start. A rail keeps the four
destinations on screen the whole time.

QToolButton, not QPushButton: it is the widget that puts a label under an icon, and it
keeps the rail out of the way of tests that look pages up by button text.
"""
from PyQt5 import QtCore, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons


class NavRail(QtWidgets.QWidget):
    """items: [(key, label, icon_name)]. Emits the key that was tapped."""

    selected = QtCore.pyqtSignal(str)

    def __init__(self, items, footer=None, parent=None):
        super(NavRail, self).__init__(parent)
        self.setObjectName("rail")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setFixedWidth(184)
        self._active = None
        self.buttons = {}
        self._icon_names = {}
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(12, 14, 12, 14)
        box.setSpacing(4)
        for key, text, icon_name in items:
            box.addWidget(self._item(key, text, icon_name))
        box.addStretch(1)
        if footer is not None:
            key, text, icon_name = footer
            box.addWidget(self._item(key, text, icon_name))

    def _item(self, key, text, icon_name):
        button = QtWidgets.QToolButton()
        button.setObjectName("railItem")
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)
        button.setText(text)
        button.setIcon(icons.icon(icon_name, 28, theme.colour("on_surface_var")))
        button.setIconSize(QtCore.QSize(28, 28))
        button.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                             QtWidgets.QSizePolicy.Fixed)
        button.setAutoRaise(True)
        button.clicked.connect(lambda _checked=False, k=key: self.selected.emit(k))
        self.buttons[key] = button
        self._icon_names[key] = icon_name
        return button

    def render(self, active):
        """Highlight one destination. Returns early when nothing moved."""
        if active == self._active:
            return
        self._active = active
        for key, button in self.buttons.items():
            is_active = key == active
            name = "railItemActive" if is_active else "railItem"
            button.setObjectName(name)
            button.style().unpolish(button)
            button.style().polish(button)
            colour = theme.colour("on_primary_container" if is_active
                                  else "on_surface_var")
            button.setIcon(icons.icon(self._icon_names[key], 28, colour))
