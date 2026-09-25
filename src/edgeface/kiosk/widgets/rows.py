# -*- coding: utf-8 -*-
"""How a patient looks as one row of a list.

A delegate rather than setItemWidget: the item keeps its own text and geometry, so
QListWidget.item(i).text(), count() and visualItemRect() all still mean what they say -
which is what both the tests and tools/viz/kiosk_screens.py drive the list through.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.kiosk import theme
from edgeface.kiosk.widgets import icons

EXTRAS = QtCore.Qt.UserRole + 1          # dict: name, code, sub, trailing, tone, trash

ROW_H = theme.ROW_H
AVATAR = 52
PAD = 18
TRASH = 56


class PatientDelegate(QtWidgets.QStyledItemDelegate):
    """Avatar, name, one supporting line, and an optional trailing note and bin."""

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), ROW_H)

    @staticmethod
    def trash_rect(rect):
        """Where the bin is drawn, so the list can tell a delete tap from a select tap."""
        return QtCore.QRect(rect.right() - TRASH - PAD // 2,
                            rect.top() + (rect.height() - TRASH) // 2, TRASH, TRASH)

    def paint(self, painter, option, index):
        extras = index.data(EXTRAS) or {}
        rect = option.rect
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        if selected:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(theme.qcolor("primary_container"))
            painter.drawRoundedRect(QtCore.QRectF(rect.adjusted(0, 2, 0, -2)), 20, 20)

        # Avatar
        middle = rect.top() + rect.height() / 2.0
        centre = QtCore.QPointF(rect.left() + PAD + AVATAR / 2.0, middle)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(theme.qcolor("primary" if selected else "surface_3"))
        painter.drawEllipse(centre, AVATAR / 2.0, AVATAR / 2.0)
        initials = "".join(part[0] for part in (extras.get("name") or "").split()[-2:])
        font = QtGui.QFont(option.font)
        font.setPixelSize(20)
        font.setWeight(QtGui.QFont.Medium)
        painter.setFont(font)
        painter.setPen(theme.qcolor("on_primary" if selected else "on_surface_var"))
        painter.drawText(QtCore.QRectF(centre.x() - AVATAR / 2.0,
                                       centre.y() - AVATAR / 2.0, AVATAR, AVATAR),
                         QtCore.Qt.AlignCenter, initials.upper())

        text_left = rect.left() + PAD + AVATAR + PAD
        trailing = extras.get("trailing") or ""
        right_edge = rect.right() - PAD
        if extras.get("trash"):
            bin_rect = self.trash_rect(rect)
            painter.translate(bin_rect.left() + (TRASH - 28) / 2.0,
                              bin_rect.top() + (TRASH - 28) / 2.0)
            icons.paint(painter, "trash", 28, theme.colour("error"), 2.0)
            painter.translate(-(bin_rect.left() + (TRASH - 28) / 2.0),
                              -(bin_rect.top() + (TRASH - 28) / 2.0))
            right_edge = bin_rect.left() - 10

        if trailing:
            font.setPixelSize(19)
            font.setWeight(QtGui.QFont.Normal)
            painter.setFont(font)
            painter.setPen(theme.qcolor("on_surface_var"))
            width = QtGui.QFontMetrics(font).width(trailing) + 4
            painter.drawText(QtCore.QRectF(right_edge - width, rect.top(), width,
                                           rect.height()),
                             QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, trailing)
            right_edge -= width + 16

        text_width = max(40, right_edge - text_left)
        font.setPixelSize(24)
        font.setWeight(QtGui.QFont.Medium)
        painter.setFont(font)
        painter.setPen(theme.qcolor("on_surface"))
        name = QtGui.QFontMetrics(font).elidedText(
            extras.get("name") or index.data() or "", QtCore.Qt.ElideRight, text_width)
        painter.drawText(QtCore.QRectF(text_left, rect.top() + 12, text_width, 28),
                         QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, name)

        sub = extras.get("sub") or ""
        if sub:
            font.setPixelSize(19)
            font.setWeight(QtGui.QFont.Normal)
            painter.setFont(font)
            painter.setPen(theme.qcolor("on_surface_var"))
            sub = QtGui.QFontMetrics(font).elidedText(sub, QtCore.Qt.ElideRight,
                                                      text_width)
            painter.drawText(QtCore.QRectF(text_left, rect.top() + 40, text_width, 24),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub)
        painter.restore()


def apply(list_widget, delete_handler=None):
    """Give a QListWidget the patient look, and optionally a working bin per row."""
    delegate = PatientDelegate(list_widget)
    list_widget.setItemDelegate(delegate)
    list_widget.setSpacing(2)
    list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
    list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    if delete_handler is not None:
        list_widget.viewport().installEventFilter(
            _BinFilter(list_widget, delegate, delete_handler))
    return delegate


class _BinFilter(QtCore.QObject):
    """Turns a tap on the bin glyph into a delete, and leaves every other tap alone."""

    def __init__(self, list_widget, delegate, handler):
        super(_BinFilter, self).__init__(list_widget)
        self.list_widget = list_widget
        self.delegate = delegate
        self.handler = handler

    def eventFilter(self, _obj, event):
        if event.type() != QtCore.QEvent.MouseButtonRelease:
            return False
        item = self.list_widget.itemAt(event.pos())
        if item is None:
            return False
        extras = item.data(EXTRAS) or {}
        if not extras.get("trash"):
            return False
        if not self.delegate.trash_rect(self.list_widget.visualItemRect(item)).contains(
                event.pos()):
            return False
        self.handler(item.data(QtCore.Qt.UserRole))
        return True                      # swallow it: this was not a row selection


def fill(list_widget, rows):
    """Rebuild the list only when the data really changed.

    Clearing a QListWidget destroys the item Qt is still delivering itemClicked for,
    which crashed the kiosk the first time a nurse tapped a patient.
    """
    key = tuple((row.get("code"), row.get("name"), row.get("sub"), row.get("trailing"),
                 bool(row.get("trash"))) for row in rows)
    if getattr(list_widget, "_rows_key", None) == key:
        return False
    list_widget._rows_key = key
    list_widget.clear()
    for row in rows:
        item = QtWidgets.QListWidgetItem(u"{}  —  {}".format(row.get("code") or "",
                                                                 row.get("name") or ""))
        item.setData(QtCore.Qt.UserRole, row.get("code"))
        item.setData(EXTRAS, row)
        item.setSizeHint(QtCore.QSize(0, ROW_H))
        list_widget.addItem(item)
    return True
