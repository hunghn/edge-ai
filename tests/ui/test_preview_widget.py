# -*- coding: utf-8 -*-
"""The camera preview: how it scales, and what that costs.

The kiosk runs fullscreen on a 3200x2000 screen, so the preview widget is large (1612 px
wide). It now gets the camera's own 1920x1080 as raw RGB (C-09); how the picture is
built and fitted was once the whole of the stutter, which is why it has tests of its own.
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


@pytest.fixture
def raw_frame():
    """A 1920x1080 raw preview as the engine writes it (common/preview_frame.py)."""
    import numpy as np

    from edgeface.common import preview_frame

    rgb = np.zeros((1080, 1920, 3), dtype=np.uint8)
    rgb[:, :, 0] = 255                          # pure red, in RGB order
    return preview_frame.encode_header(1920, 1080) + rgb.tobytes()


def test_a_raw_frame_is_shown_at_full_resolution_in_its_own_colours(qt_app, raw_frame):
    from PyQt5 import QtGui

    widget = PreviewWidget()
    assert widget.show_frame(raw_frame) is True
    assert (widget._pixmap.width(), widget._pixmap.height()) == (1920, 1080)
    colour = QtGui.QColor(widget._pixmap.toImage().pixel(5, 5))
    assert (colour.red(), colour.green(), colour.blue()) == (255, 0, 0)


def test_a_torn_or_foreign_raw_frame_is_refused(qt_app, raw_frame, jpeg):
    widget = PreviewWidget()
    assert widget.show_frame(raw_frame[:-10]) is False           # written half-way
    assert widget.show_frame(b"EFP1" + b"\x00" * 4) is False    # 0x0 picture
    assert widget.show_frame(jpeg) is True                       # JPEG still works
    assert widget.show_frame(raw_frame) is True


def test_fitting_a_1080p_frame_stays_under_the_frame_budget(qt_app, raw_frame):
    """Building the picture plus one paint into the 1612 px panel, per frame."""
    from PyQt5 import QtGui

    widget = PreviewWidget()
    widget.resize(1612, 1644)
    canvas = QtGui.QPixmap(1612, 1644)
    started = time.time()
    for _ in range(10):
        widget.show_frame(raw_frame)
        painter = QtGui.QPainter(canvas)
        painter.drawPixmap(widget.target_rect(), widget._pixmap)
        painter.end()
    per_frame_ms = (time.time() - started) / 10.0 * 1000.0
    assert per_frame_ms < 40.0, "{:.1f} ms per frame".format(per_frame_ms)
