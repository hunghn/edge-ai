# -*- coding: utf-8 -*-
"""Haar cascade detection for the baseline.

Deliberately the classic recipe — grayscale, equalised, `detectMultiScale` — so the
comparison with SCRFD is between the methods, not between two differently tuned
pipelines.
"""
import os

import cv2
import numpy as np

from edgeface.common.timing import timed

# JetPack 4.6 ships the cascades in /usr/share/opencv4 (only the `alt*` variants). Older
# pip wheels put them in cv2.data; OpenCV 5 wheels ship none at all, which is why
# models/cascades/ and EDGEFACE_CASCADE_DIR exist as a fallback for dev machines.
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CASCADE_DIRS = ("/usr/share/opencv4/haarcascades", "/usr/share/opencv/haarcascades",
                os.path.join(REPO, "models", "cascades"))
CASCADE_NAMES = ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml",
                 "haarcascade_frontalface_alt.xml")


def cascade_dirs():
    dirs = []
    from_env = os.environ.get("EDGEFACE_CASCADE_DIR")
    if from_env:
        dirs.append(from_env)
    data_dir = getattr(getattr(cv2, "data", None), "haarcascades", None)
    if data_dir:
        dirs.append(data_dir)
    dirs.extend(CASCADE_DIRS)
    return dirs


def find_cascade(name=None):
    """First frontal-face cascade available. Which variant is used goes in the report."""
    names = (name,) if name else CASCADE_NAMES
    candidates = [os.path.join(directory, filename)
                  for directory in cascade_dirs() for filename in names]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise RuntimeError(
        "no Haar cascade found. Looked in {}. On a dev machine, copy one from the Nano:\n"
        "  scp nano:/usr/share/opencv4/haarcascades/haarcascade_frontalface_alt2.xml "
        "models/cascades/".format(cascade_dirs()))


class HaarDetector(object):
    def __init__(self, cascade_path=None, scale_factor=1.1, min_neighbors=5,
                 min_size=60):
        self.path = cascade_path or find_cascade()
        self.cascade = cv2.CascadeClassifier(self.path)
        if self.cascade.empty():
            raise RuntimeError("could not load cascade " + self.path)
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size

    @timed("B1")
    def detect(self, image):
        """[(x1, y1, x2, y2)] sorted by area, largest first."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        gray = cv2.equalizeHist(gray)
        boxes = self.cascade.detectMultiScale(
            gray, scaleFactor=self.scale_factor, minNeighbors=self.min_neighbors,
            minSize=(self.min_size, self.min_size))
        result = [(float(x), float(y), float(x + w), float(y + h)) for x, y, w, h in boxes]
        result.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
        return result

    def largest(self, image):
        boxes = self.detect(image)
        return boxes[0] if boxes else None


@timed("B2")
def face_chip(image, box, size=128):
    """Grayscale, equalised, fixed-size crop — what LBPH is trained and queried on.

    LBPH has no alignment step of its own, which is one of the reasons it struggles with
    pose; the baseline must show that honestly rather than borrow SCRFD's landmarks.
    """
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    height, width = image.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    crop = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return cv2.equalizeHist(cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA))


def detector_from_config(cfg):
    baseline = cfg.get("baseline") or {}
    return HaarDetector(cascade_path=baseline.get("cascade_path"),
                        scale_factor=baseline.get("scale_factor", 1.1),
                        min_neighbors=baseline.get("min_neighbors", 5),
                        min_size=baseline.get("min_face_px", 60))
