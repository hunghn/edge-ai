"""S0: capture thread and a one-slot ring buffer.

The engine must always work on the newest frame. Anything older is dropped rather than
queued, so latency cannot grow when a frame takes longer than usual to process.

Sources: GStreamer (the device, C-12: USB webcam via v4l2src + MJPG), a video file and a
plain V4L2 index for development.
"""
import threading
import time

import cv2

from edgeface.common.log import get_logger
from edgeface.types import Frame

LOG = get_logger("capture")


class RingBuffer(object):
    """One slot. put() overwrites, get_latest() waits for something newer."""

    def __init__(self):
        self._condition = threading.Condition()
        self._frame = None
        self.dropped = 0
        self.received = 0

    def put(self, frame):
        with self._condition:
            if self._frame is not None:
                self.dropped += 1       # the consumer never saw the previous frame
            self._frame = frame
            self.received += 1
            self._condition.notify_all()

    def get_latest(self, after_id=-1, timeout=1.0):
        """Newest frame with frame_id > after_id, or None on timeout."""
        deadline = time.time() + timeout
        with self._condition:
            while True:
                frame = self._frame
                if frame is not None and frame.frame_id > after_id:
                    self._frame = None  # consumed: the next put() is not a drop
                    return frame
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def peek(self):
        with self._condition:
            return self._frame


class FrameSource(object):
    """cv2.VideoCapture wrapper: open(), read() -> image or None, release()."""

    def __init__(self, description):
        self.description = description
        self._cap = None

    def _open_capture(self):
        raise NotImplementedError

    def open(self):
        self._cap = self._open_capture()
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError("cannot open capture source: {}".format(self.description))
        return self

    def read(self):
        if self._cap is None:
            return None
        got, image = self._cap.read()
        return image if got else None

    def release(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def is_open(self):
        return self._cap is not None and self._cap.isOpened()


class GStreamerSource(FrameSource):
    def __init__(self, pipeline):
        super(GStreamerSource, self).__init__("gstreamer: {}".format(pipeline[:60]))
        self.pipeline = pipeline

    def _open_capture(self):
        return cv2.VideoCapture(self.pipeline, cv2.CAP_GSTREAMER)


class UsbSource(FrameSource):
    def __init__(self, index=0, width=None, height=None, fourcc="MJPG"):
        super(UsbSource, self).__init__("v4l2 index {}".format(index))
        self.index, self.width, self.height, self.fourcc = index, width, height, fourcc

    def _open_capture(self):
        cap = cv2.VideoCapture(self.index, cv2.CAP_V4L2)
        if self.fourcc:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        if self.width:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap


class FileSource(FrameSource):
    """Recorded video. realtime=True paces playback, loop=True restarts at the end."""

    def __init__(self, path, realtime=False, fps=None, loop=False):
        super(FileSource, self).__init__("file: {}".format(path))
        self.path, self.realtime, self.loop = path, realtime, loop
        self.fps = fps
        self.eof = False
        self._next_due = None

    def _open_capture(self):
        cap = cv2.VideoCapture(self.path)
        if self.fps is None and cap.isOpened():
            reported = cap.get(cv2.CAP_PROP_FPS)
            self.fps = reported if reported and reported > 0 else 15.0
        return cap

    def read(self):
        if self.realtime and self._next_due is not None:
            delay = self._next_due - time.time()
            if delay > 0:
                time.sleep(delay)
        image = super(FileSource, self).read()
        if image is None:
            if self.loop and self._cap is not None:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                image = super(FileSource, self).read()
            if image is None:
                self.eof = True
                return None
        period = 1.0 / float(self.fps or 15.0)
        self._next_due = (self._next_due or time.time()) + period
        return image


def source_from_config(cfg):
    capture_cfg = cfg["capture"]
    kind = capture_cfg["source"]
    if kind == "gstreamer":
        return GStreamerSource(capture_cfg["pipeline"])
    if kind == "usb":
        return UsbSource(capture_cfg.get("usb_index", 0), capture_cfg.get("width"),
                         capture_cfg.get("height"), capture_cfg.get("fourcc", "MJPG"))
    if kind == "file":
        return FileSource(capture_cfg["path"], capture_cfg.get("realtime", True),
                          capture_cfg.get("fps"), capture_cfg.get("loop", False))
    raise ValueError("unknown capture source: {}".format(kind))


class CaptureThread(object):
    """Reads a FrameSource into a RingBuffer, reopening the camera when it disappears."""

    def __init__(self, source, ring=None, read_fail_max=30, reconnect_s=2.0):
        self.source = source
        self.ring = ring or RingBuffer()
        self.read_fail_max = read_fail_max
        self.reconnect_s = reconnect_s
        self.frame_id = 0
        self.error = None
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.source.open()
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()
        return self

    def _run(self):
        failures = 0
        while not self._stop.is_set():
            image = self.source.read()
            if image is None:
                if getattr(self.source, "eof", False):
                    LOG.info("end of video source")
                    break
                failures += 1
                if failures >= self.read_fail_max:
                    self.error = "camera_lost"
                    LOG.warning("camera lost after %d failed reads; reopening", failures)
                    self._reopen()
                    failures = 0
                continue
            failures = 0
            self.error = None
            self.frame_id += 1
            self.ring.put(Frame(self.frame_id, time.time(), image))

    def _reopen(self):
        try:
            self.source.release()
        except Exception:  # pragma: no cover - best effort
            pass
        while not self._stop.is_set():
            time.sleep(self.reconnect_s)
            try:
                self.source.open()
                LOG.info("camera reopened")
                self.error = None
                return
            except RuntimeError as exc:
                LOG.warning("reopen failed: %s", exc)

    def stop(self, timeout=2.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.source.release()
        return self

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()
