"""S2: pick the one person standing at the kiosk.

The largest face is chosen first and only then checked against the ROI, so a person
standing slightly off-centre is told to move instead of the system silently picking
someone further back.
"""
from edgeface.common.geometry import bbox_area, bbox_center, bbox_min_side, point_in_rect
from edgeface.common.log import get_logger
from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import GuidanceCode

LOG = get_logger("subject")
_warned = set()


def _warn_once(key, message):
    if key not in _warned:
        _warned.add(key)
        LOG.warning(message)


def roi_rect(cfg, width, height):
    """ROI in pixels, or the whole frame while subject.roi is still null (D-06)."""
    roi = cfg["subject"].get("roi")
    if not roi:
        _warn_once("roi", "subject.roi is null (D-06): using the whole frame")
        return [0.0, 0.0, float(width - 1), float(height - 1)]
    return [roi[0] * width, roi[1] * height, roi[2] * width, roi[3] * height]


def min_side_in_frame(cfg, width, height):
    """subject.min_side_px expressed in full-frame pixels.

    The spec's 110 px can refer to the 640x640 detector input or to the full frame; the
    two differ by the letterbox factor (D-07). subject.min_side_space selects which.
    """
    subject_cfg = cfg["subject"]
    min_side = subject_cfg["min_side_px"]
    space = subject_cfg.get("min_side_space", "det")
    if space == "frame":
        return float(min_side)
    det_size = cfg["detect"]["input_size"][0]
    scale = float(det_size) / max(width, height)   # same factor as imgproc.letterbox
    return float(min_side) / scale


@timed("S2")
def choose_subject(detections, image_shape, cfg):
    """One Detection, or a guidance code telling the person how to stand."""
    if not detections:
        return fail(GuidanceCode.NO_FACE, None)
    height, width = image_shape[:2]
    candidate = max(detections, key=lambda d: (bbox_area(d.bbox), d.score))
    if not point_in_rect(bbox_center(candidate.bbox), roi_rect(cfg, width, height)):
        return fail(GuidanceCode.MOVE_TO_CENTER, candidate)
    if bbox_min_side(candidate.bbox) < min_side_in_frame(cfg, width, height):
        return fail(GuidanceCode.STEP_CLOSER, candidate)
    return ok(candidate)
