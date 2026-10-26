# -*- coding: utf-8 -*-
"""Camera preview: the frame the engine drops in /dev/shm, plus the ROI outline.

The engine writes the camera's own 1920x1080 as raw RGB behind a small header (C-09,
engine/publisher.py), or a JPEG when kiosk.preview_format says so; the first bytes tell
which. Raw is what makes full resolution affordable here: building the image from it
costs about 10 ms on the Nano, decoding a 1080p JPEG 32 ms, on the UI thread.

The picture is kept at the size the engine wrote it and fitted to the widget while
painting, never by building a scaled copy. On a 4K screen
`QPixmap.scaled(..., SmoothTransformation)` cost 44.5 ms per frame and allocated a 13 MB
pixmap each time, which was a stutter. Painting straight into the widget rectangle
costs a few ms and allocates nothing.
"""
from PyQt5 import QtCore, QtGui, QtWidgets

from edgeface.common import preview_frame


class PreviewWidget(QtWidgets.QLabel):
    def __init__(self, parent=None, roi=None):
        super(PreviewWidget, self).__init__(parent)
        self.setObjectName("preview")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setMinimumSize(480, 270)
        self.roi = roi                       # (x1, y1, x2, y2) as fractions, or None
        self._pixmap = None

    def show_frame(self, data):
        """Returns False when the bytes are not a readable image (engine mid-write)."""
        if not data:
            return False
        size = preview_frame.decode_header(data)
        if size is not None:
            width, height = size
            if width == 0 or height == 0 or len(data) != preview_frame.expected_size(
                    width, height):
                return False
            # QImage only borrows the bytes; fromImage() copies them before `data` goes.
            image = QtGui.QImage(data[preview_frame.RAW_HEADER.size:], width, height,
                                 width * 3, QtGui.QImage.Format_RGB888)
        else:
            image = QtGui.QImage.fromData(data, "JPG")
        if image.isNull():
            return False
        self._pixmap = QtGui.QPixmap.fromImage(image)
        self.update()                        # repaint; the scaling happens there
        return True

    show_jpeg = show_frame                   # the name it had while only JPEG arrived

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
