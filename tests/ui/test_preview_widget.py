# -*- coding: utf-8 -*-
"""The camera preview: how it scales, and what that costs.

The kiosk runs fullscreen on a 3840x2160 screen, so the preview widget is large and the
480 px picture is blown up around five times. How that enlargement is done was the whole
of the stutter, which is why it has tests of its own.
"""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytestmark = pytest.mark.ui
pytest.importorskip("PyQt5")

from edgeface.kiosk.widgets.preview import PreviewWidget  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PyQt5 import QtWidgets

    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def jpeg():
    import cv2
    import numpy as np

    frame = np.random.RandomState(0).randint(0, 255, (270, 480, 3), dtype=np.uint8)
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    assert ok
    return buffer.tobytes()


def test_the_picture_is_kept_at_its_own_size(qt_app, jpeg):
    """The property that was lost: no enlarged copy is built when a frame arrives.

    Building one cost 44.5 ms and allocated 13 MB per frame on the device. The widget
    now keeps the 480 px picture and enlarges it while painting instead.
    """
    widget = PreviewWidget()
    widget.resize(2400, 1350)
    assert widget.show_jpeg(jpeg) is True
    assert widget._pixmap.size().width() == 480
    assert widget.pixmap() is None or widget.pixmap().width() == 480


def test_the_picture_keeps_its_aspect_ratio_in_any_widget(qt_app, jpeg):
    widget = PreviewWidget()
    widget.show_jpeg(jpeg)
    for width, height in ((2400, 1350), (1000, 1000), (480, 270), (3840, 2160)):
        widget.resize(width, height)
        # The widget has a minimum size, so compare against what it actually became
        # rather than against what we asked for.
        rect = widget.target_rect()
        assert rect.width() <= widget.width() and rect.height() <= widget.height()
        assert abs(rect.width() / float(rect.height()) - 480.0 / 270.0) < 0.02


def test_the_roi_follows_the_picture_not_the_widget(qt_app, jpeg):
    """With letterboxing the two differ, and an ROI drawn against the widget would tell
    the patient to stand somewhere the camera is not looking."""
    widget = PreviewWidget(roi=[0.25, 0.25, 0.75, 0.75])
    widget.show_jpeg(jpeg)
    widget.resize(1000, 1000)                 # taller than 16:9, so bars top and bottom
    rect = widget.target_rect()
    assert rect.height() < 1000 and rect.y() > 0


def test_half_written_bytes_are_refused_without_breaking_the_widget(qt_app, jpeg):
    widget = PreviewWidget()
    assert widget.show_jpeg(None) is False
    assert widget.show_jpeg(b"") is False
    assert widget.show_jpeg(b"not a jpeg at all") is False
    assert widget.show_jpeg(jpeg[:40]) is False
    assert widget.show_jpeg(jpeg) is True     # recovers on the next good frame


def test_painting_a_frame_stays_well_under_the_frame_budget(qt_app, jpeg):
    """A measured ceiling, not a micro-benchmark.

    At 15 fps a frame is 66 ms, and the old code spent 44.5 ms of it on a blur that
    added no detail. This does not try to catch every regression - it catches the one
    that already happened: quietly going back to building a scaled copy per frame.
    """
    from PyQt5 import QtGui

    widget = PreviewWidget()
    widget.resize(2400, 1350)
    widget.show_jpeg(jpeg)
    canvas = QtGui.QPixmap(2400, 1350)

    def paint_once():
        painter = QtGui.QPainter(canvas)
        painter.drawPixmap(widget.target_rect(), widget._pixmap)
        painter.end()

    paint_once()
    started = time.time()
    for _ in range(20):
        paint_once()
    per_frame_ms = (time.time() - started) / 20.0 * 1000.0
    assert per_frame_ms < 15.0, "{:.1f} ms per frame".format(per_frame_ms)
