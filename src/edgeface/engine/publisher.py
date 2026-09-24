"""Everything the engine sends outwards: kiosk state, camera preview, outbox events.

Two rules shape this module. State is published only when it changes (or every half
second), because the kiosk polls a row on an SD card and there is no point writing 15
times a second. And the preview is a file in /dev/shm, not a database blob: SQLite is
for state, shared memory is for pixels.
"""
import json
import os

import cv2

from edgeface.common.log import get_logger
from edgeface.storage import clock, kiosk_ipc
from edgeface.storage.db import transaction

LOG = get_logger("publisher")

HEARTBEAT_S = 0.5


class Publisher(object):
    def __init__(self, conn, cfg):
        self.conn = conn
        self.cfg = cfg
        kiosk_cfg = cfg.get("kiosk") or {}
        self.preview_path = kiosk_cfg.get("preview_path", "/dev/shm/edgeface/preview.jpg")
        self.preview_width = int(kiosk_cfg.get("preview_width", 480))
        self.preview_period = 1.0 / float(kiosk_cfg.get("preview_fps", 5) or 5)
        self._last_key = None
        self._last_args = None
        self._last_publish = 0.0
        self._last_preview = 0.0

    def publish(self, state, guidance=None, session_id=None, payload=None, now=None,
                force=False):
        """Write kiosk_state when something changed, or every HEARTBEAT_S regardless."""
        now = clock.now() if now is None else now
        key = (state, guidance, session_id, json.dumps(payload, sort_keys=True)
               if payload else None)
        if not force and key == self._last_key and (now - self._last_publish) < HEARTBEAT_S:
            return None
        with transaction(self.conn):
            seq = kiosk_ipc.publish_state(self.conn, state, guidance, session_id, payload, now)
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

    def write_preview(self, image, box=None, now=None, good=False):
        """Downscaled JPEG for the kiosk: temp file then rename, so no torn reads.

        `box` is the face rectangle as fractions of the frame, (x1, y1, x2, y2), or None
        when nothing is detected. It is drawn here rather than published in kiosk_state:
        the state row lives on the SD card and is only meant to be written when something
        changes, whereas a box that follows a face changes on every frame. Drawing it into
        the picture also keeps the two in step — a box travelling through the database
        while the pixels travel through /dev/shm would always lag the face it outlines.
        """
        now = clock.now() if now is None else now
        if (now - self._last_preview) < self.preview_period:
            return False
        directory = os.path.dirname(self.preview_path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        height, width = image.shape[:2]
        scale = float(self.preview_width) / width
        small = cv2.resize(image, (self.preview_width, max(1, int(round(height * scale)))))
        if box is not None:
            self._draw_box(small, box, good)
        # Encode in memory: cv2.imwrite picks its codec from the file extension, and the
        # temp file cannot be called .jpg or the kiosk might read it half-written.
        ok, buffer = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            LOG.warning("could not encode the preview frame")
            return False
        tmp = self.preview_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(buffer.tobytes())
        os.rename(tmp, self.preview_path)
        self._last_preview = now
        return True

    @staticmethod
    def _draw_box(small, box, good):
        """Outline the face on the already-downscaled preview.

        Green once the frame has passed every gate, amber while the pipeline still has
        something to say about it, so a patient can see when the system is satisfied
        without reading the instruction.
        """
        height, width = small.shape[:2]
        x1 = int(round(max(0.0, min(1.0, box[0])) * width))
        y1 = int(round(max(0.0, min(1.0, box[1])) * height))
        x2 = int(round(max(0.0, min(1.0, box[2])) * width))
        y2 = int(round(max(0.0, min(1.0, box[3])) * height))
        if x2 <= x1 or y2 <= y1:
            return
        colour = (162, 224, 126) if good else (90, 190, 240)     # BGR
        cv2.rectangle(small, (x1, y1), (x2, y2), colour, 2)

    def claim_commands(self, now=None):
        return kiosk_ipc.claim_commands(self.conn, at=now)
