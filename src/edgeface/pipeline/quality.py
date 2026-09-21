"""S5 (IQA half): blur and luminance of the face region.

Laplacian variance depends on how many pixels the face covers, so the measurement area
must be fixed or the threshold means nothing: the face box is shrunk (to drop
background), clipped to the frame and resized to a fixed square before measuring (D-11).
"""
import cv2
import numpy as np

from edgeface.common.geometry import clip_bbox, expand_bbox
from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import GuidanceCode


def face_patch(image, bbox, shrink=0.8, size=112):
    """Grayscale, fixed-size crop of the face used for both blur and luminance."""
    height, width = image.shape[:2]
    box = clip_bbox(expand_bbox(bbox, shrink), width, height)
    x1, y1, x2, y2 = (int(round(v)) for v in box)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    patch = image[y1:y2, x1:x2]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY) if patch.ndim == 3 else patch
    return cv2.resize(gray, (size, size), interpolation=cv2.INTER_AREA)


def measure(image, bbox, shrink=0.8, size=112):
    """{'blur', 'lum'}: Laplacian variance and mean gray level. None if the crop is empty."""
    gray = face_patch(image, bbox, shrink, size)
    if gray is None:
        return None
    return {"blur": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
            "lum": float(np.mean(gray))}


@timed("S5")
def image_quality(image, bbox, cfg):
    """S5 (IQA half). Luminance is reported before blur: a nurse can fix the lighting,
    but "hold still" is useless advice in a dark room."""
    iqa_cfg = cfg["iqa"]
    metrics = measure(image, bbox, iqa_cfg.get("crop_shrink", 0.8),
                      iqa_cfg.get("crop_size", 112))
    if metrics is None:
        return fail(GuidanceCode.INVALID_BBOX, None)
    if metrics["lum"] < iqa_cfg["lum_min"]:
        return fail(GuidanceCode.TOO_DARK, metrics)
    if metrics["lum"] > iqa_cfg["lum_max"]:
        return fail(GuidanceCode.TOO_BRIGHT, metrics)
    if metrics["blur"] < iqa_cfg["blur_min"]:
        return fail(GuidanceCode.HOLD_STILL, metrics)
    return ok(metrics)
