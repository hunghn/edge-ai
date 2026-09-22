# -*- coding: utf-8 -*-
"""Camera preview: the JPEG the engine drops in /dev/shm, plus the ROI outline."""
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
        self.setPixmap(self._pixmap.scaled(self.size(), QtCore.Qt.KeepAspectRatio,
                                           QtCore.Qt.SmoothTransformation))
        return True

    def paintEvent(self, event):
        super(PreviewWidget, self).paintEvent(event)
        if not self.roi or self._pixmap is None:
            return
        painter = QtGui.QPainter(self)
        pen = QtGui.QPen(QtGui.QColor("#7ee0a2"), 3, QtCore.Qt.DashLine)
        painter.setPen(pen)
        width, height = self.width(), self.height()
        painter.drawRect(int(self.roi[0] * width), int(self.roi[1] * height),
                         int((self.roi[2] - self.roi[0]) * width),
                         int((self.roi[3] - self.roi[1]) * height))
        painter.end()
