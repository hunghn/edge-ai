"""Everything the engine sends outwards: kiosk state, camera preview, outbox events.

Two rules shape this module. State is published only when it changes (or every half
second), because the kiosk polls a row on an SD card and there is no point writing 15
times a second. And the preview is a file in /dev/shm, not a database blob: SQLite is
for state, shared memory is for pixels.

The preview is the camera's own 1920x1080, uncompressed (C-09, 2026-10-08). The kiosk
shows it in a 1612 px panel on a 3200x2000 screen, and the 480 px JPEG it used to get
was enlarged 3.4 times, which is what looked blurred. Measured on the Nano per frame:
JPEG at 1920 costs 37 ms to encode and 32 ms to decode on the kiosk's UI thread; raw RGB
costs 22 ms to write and about 10 ms to read. The writing happens on a thread of its own
(PreviewWriter), so the recognition loop never waits for it.
"""
import json
import os
import threading
import time

import cv2

from edgeface.common import preview_frame
from edgeface.common.log import get_logger
from edgeface.storage import clock, kiosk_ipc
from edgeface.storage.db import transaction

LOG = get_logger("publisher")

HEARTBEAT_S = 0.5

# Payload blocks that move on their own. They are carried to the kiosk but never counted
# as "something changed": blur and yaw differ on every frame, so letting them into the
# comparison would turn a row written on change into a row written fifteen times a
# second. They ride along with the next publish, which is at most one every HEARTBEAT_S.
VOLATILE = ("telemetry", "device")

FORMATS = ("raw", "jpeg")             # kiosk.preview_format; raw: common/preview_frame.py
# The box outline was tuned on a 480 px preview; wider pictures get a thicker line so it
# looks the same once the kiosk fits the picture to its panel.
BOX_LINE_PX_AT_480 = 2


class PreviewWriter(object):
    """Writes the newest preview frame on its own thread.

    submit() only swaps a reference under a lock, so the S1-S10 loop pays nothing for a
    1080p picture. The thread wakes when a frame arrives, writes at most one every
    `period` seconds, and skips any it could not get to: only the newest frame matters
    to the person looking at the screen. cv2.cvtColor and file writes release the GIL,
    so the work lands on another core.
    """

    def __init__(self, publisher, period):
        self.publisher = publisher
        self.period = float(period)
        self._condition = threading.Condition()
        self._pending = None
        self._stop = False
        self._thread = None
        self.written = 0

    def start(self):
        if self._thread is None:
            self._stop = False
            self._thread = threading.Thread(target=self._run, name="preview")
            self._thread.daemon = True
            self._thread.start()
        return self

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def submit(self, image, box=None, good=False):
        with self._condition:
            self._pending = (image, box, good)
            self._condition.notify()

    def stop(self, timeout=2.0):
        with self._condition:
            self._stop = True
            self._condition.notify()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self):
        last = 0.0
        while True:
            with self._condition:
                while self._pending is None and not self._stop:
                    self._condition.wait()
                if self._stop:
                    return
                wait = self.period - (time.monotonic() - last)
                if wait > 0:
                    # Not yet: wait out the rest of the period, then take whatever is
                    # newest by then rather than the frame that woke us.
                    self._condition.wait(wait)
                    if self._stop:
                        return
                image, box, good = self._pending
                self._pending = None
            try:
                self.publisher.store_preview(image, box, good)
                self.written += 1
            except Exception:                     # noqa: BLE001 - never kill the thread
                LOG.exception("could not write the preview frame")
            last = time.monotonic()


class Publisher(object):
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        kiosk_cfg = cfg.get("kiosk") or {}
        self.preview_path = kiosk_cfg.get("preview_path", "/dev/shm/edgeface/preview.rgb")
        self.preview_format = kiosk_cfg.get("preview_format", "raw")
        width = kiosk_cfg.get("preview_width")
        self.preview_width = int(width) if width else None     # None: the camera's own
        self.preview_quality = int(kiosk_cfg.get("preview_jpeg_quality", 85))
        self.preview_period = 1.0 / float(kiosk_cfg.get("preview_fps", 5) or 5)
        self.preview_writer = None
        self._last_key = None
        self._last_args = None
        self._last_publish = 0.0
        self._last_preview = 0.0
        self._device = {}
        self._fps = None

    def set_device(self, metrics):
        """RAM, temperature and CPU for the status screen. {} when nothing reads them."""
        self._device = dict(metrics or {})

    def set_fps(self, fps):
        self._fps = None if fps is None else round(float(fps), 1)

    @staticmethod
    def _key(state, guidance, session_id, payload):
        stable = None
        if payload:
            stable = dict((k, v) for k, v in payload.items() if k not in VOLATILE)
        return (state, guidance, session_id,
                json.dumps(stable, sort_keys=True) if stable else None)

    def _augment(self, payload):
        """Fold in the engine-wide numbers just before the row is written.

        Kept out of _last_args so a heartbeat carries today's frame rate rather than
        re-publishing the one measured when the state last changed.
        """
        if not self._device and self._fps is None:
            return payload
        body = dict(payload or {})
        if self._device:
            body["device"] = self._device
        if self._fps is not None:
            numbers = dict(body.get("telemetry") or {})
            numbers["fps"] = self._fps
            body["telemetry"] = numbers
        return body

    def publish(self, state, guidance=None, session_id=None, payload=None, now=None,
                force=False):
        """Write kiosk_state when something changed, or every HEARTBEAT_S regardless."""
        now = clock.now() if now is None else now
        key = self._key(state, guidance, session_id, payload)
        if not force and key == self._last_key and (now - self._last_publish) < HEARTBEAT_S:
            return None
        body = self._augment(payload)
        with transaction(self.conn):
            seq = kiosk_ipc.publish_state(self.conn, state, guidance, session_id, body, now)
        self._last_key = key
        self._last_args = (state, guidance, session_id, payload)
        self._last_publish = now
        return seq

    def heartbeat(self, now=None):
        """Re-publish the current state so the kiosk can tell the engine is alive.

        Without this the row goes stale while the nurse thinks (up to 30 s, C-21) and the
        kiosk would show "engine down" after five seconds. Debouncing keeps it to one
        write every HEARTBEAT_S.
        """
        if self._last_args is None:
            return None
        state, guidance, session_id, payload = self._last_args
        return self.publish(state, guidance, session_id, payload, now)

    def start_preview_thread(self):
        """Hand preview writing to a thread of its own (the engine does this at start)."""
        if self.preview_writer is None:
            self.preview_writer = PreviewWriter(self, self.preview_period)
        self.preview_writer.start()
        return self.preview_writer

    def stop_preview_thread(self):
        if self.preview_writer is not None:
            self.preview_writer.stop()

    def write_preview(self, image, box=None, now=None, good=False):
        """Publish one camera frame for the kiosk, at most preview_fps times a second.

        `box` is the face rectangle as fractions of the frame, (x1, y1, x2, y2), or None
        when nothing is detected. It is drawn here rather than published in kiosk_state:
        the state row lives on the SD card and is only meant to be written when something
        changes, whereas a box that follows a face changes on every frame. Drawing it into
        the picture also keeps the two in step — a box travelling through the database
        while the pixels travel through /dev/shm would always lag the face it outlines.

        With the preview thread running this only hands the frame over; without it (the
        tests, offline tools) the file is written here and now.
        """
        now = clock.now() if now is None else now
        if (now - self._last_preview) < self.preview_period:
            return False
        self._last_preview = now
        writer = self.preview_writer
        if writer is not None and writer.is_running():
            writer.submit(image, box, good)
            return True
        return self.store_preview(image, box, good)

    def render_preview(self, image, box=None, good=False):
        """The picture that goes into the file: a new array, never the camera's frame.

        raw  -> RGB at the camera's size (or preview_width, when set)
        jpeg -> BGR, for cv2.imencode
        """
        height, width = image.shape[:2]
        resized = bool(self.preview_width) and self.preview_width != width
        if resized:
            size = (self.preview_width, max(1, int(round(height * self.preview_width
                                                         / float(width)))))
            image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        if self.preview_format == "raw":
            picture = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)      # a new array
        else:
            # resize already made a new array; otherwise copy, so that the box is never
            # drawn onto the frame the pipeline is still using.
            picture = image if resized else image.copy()
        if box is not None:
            self._draw_box(picture, box, good, rgb=self.preview_format == "raw")
        return picture

    def store_preview(self, image, box=None, good=False):
        """Render and write one frame: temp file then rename, so no torn reads."""
        directory = os.path.dirname(self.preview_path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        picture = self.render_preview(image, box, good)
        tmp = self.preview_path + ".tmp"
        if self.preview_format == "raw":
            height, width = picture.shape[:2]
            with open(tmp, "wb") as f:
                f.write(preview_frame.encode_header(width, height))
                # The array's own buffer: tobytes() would copy 6 MB while holding the GIL.
                f.write(memoryview(picture).cast("B"))
        else:
            # Encode in memory: cv2.imwrite picks its codec from the file extension, and
            # the temp file cannot be called .jpg or the kiosk might read it half-written.
            ok, buffer = cv2.imencode(".jpg", picture,
                                      [int(cv2.IMWRITE_JPEG_QUALITY), self.preview_quality])
            if not ok:
                LOG.warning("could not encode the preview frame")
                return False
            with open(tmp, "wb") as f:
                f.write(buffer.tobytes())
        os.rename(tmp, self.preview_path)
        return True

    @staticmethod
    def _draw_box(picture, box, good, rgb=False):
        """Outline the face on the preview picture.

        Green once the frame has passed every gate, amber while the pipeline still has
        something to say about it, so a patient can see when the system is satisfied
        without reading the instruction.
        """
        height, width = picture.shape[:2]
        x1 = int(round(max(0.0, min(1.0, box[0])) * width))
        y1 = int(round(max(0.0, min(1.0, box[1])) * height))
        x2 = int(round(max(0.0, min(1.0, box[2])) * width))
        y2 = int(round(max(0.0, min(1.0, box[3])) * height))
        if x2 <= x1 or y2 <= y1:
            return
        colour = (162, 224, 126) if good else (90, 190, 240)     # BGR
        if rgb:
            colour = colour[::-1]
        thickness = max(BOX_LINE_PX_AT_480, int(round(BOX_LINE_PX_AT_480 * width / 480.0)))
        cv2.rectangle(picture, (x1, y1), (x2, y2), colour, thickness)

    def claim_commands(self, now=None):
        return kiosk_ipc.claim_commands(self.conn, at=now)
