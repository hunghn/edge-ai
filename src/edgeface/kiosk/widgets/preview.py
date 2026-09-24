# -*- coding: utf-8 -*-
"""Camera preview: the JPEG the engine drops in /dev/shm, plus the ROI outline.

The picture is kept at the size the engine wrote it (480 px wide) and enlarged while
painting, never by building a scaled copy. On the 3840x2160 screen this kiosk runs on,
`QPixmap.scaled(..., SmoothTransformation)` cost 44.5 ms per frame and allocated a 13 MB
pixmap each time, which was the stutter. Painting straight into the widget rectangle
costs 5.3 ms and allocates nothing (measured on the Nano).

Smoothing bought nothing anyway: the detail was destroyed when the engine scaled the
frame down from 1920 to 480, and no filter puts it back. It was paying 44.5 ms to blur.
"""
from PyQt5 import QtCore, QtGui, QtWidgets


class PreviewWidget(QtWidgets.QLabel):
    def __init__(self, parent=None, roi=None):
        super(PreviewWidget, self).__init__(parent)
        self.setObjectName("preview")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.roi = roi                       # (x1, y1, x2, y2) as fractions, or None
        self._pixmap = None

    def show_jpeg(self, data):
        """Returns False when the bytes are not a readable image (engine mid-write)."""
        if not data:
            return False
        image = QtGui.QImage.fromData(data, "JPG")
        if image.isNull():
            return False
        self._pixmap = QtGui.QPixmap.fromImage(image)
        self.update()                        # repaint; the scaling happens there
        return True

    def target_rect(self):
        """Where the picture lands inside the widget, keeping its aspect ratio."""
        if self._pixmap is None or self._pixmap.isNull():
            return QtCore.QRect()
        size = self._pixmap.size()
        size.scale(self.size(), QtCore.Qt.KeepAspectRatio)
        return QtCore.QRect(QtCore.QPoint((self.width() - size.width()) // 2,
                                          (self.height() - size.height()) // 2), size)

    def paintEvent(self, event):
        super(PreviewWidget, self).paintEvent(event)
        if self._pixmap is None:
            return
        rect = self.target_rect()
        if rect.isEmpty():
            return
        painter = QtGui.QPainter(self)
        painter.drawPixmap(rect, self._pixmap)
        if self.roi:
            # Against the picture, not the widget: with letterboxing the two differ, and
            # an ROI drawn on the widget would tell the patient to stand in the wrong place.
            pen = QtGui.QPen(QtGui.QColor("#7ee0a2"), 3, QtCore.Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(int(rect.x() + self.roi[0] * rect.width()),
                             int(rect.y() + self.roi[1] * rect.height()),
                             int((self.roi[2] - self.roi[0]) * rect.width()),
                             int((self.roi[3] - self.roi[1]) * rect.height()))
        painter.end()
