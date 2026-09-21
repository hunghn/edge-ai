"""S1: SCRFD detection. The model wrapper does the work; this is the gate."""
from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import GuidanceCode


@timed("S1")
def detect(frame_image, detector, cfg):
    """[Detection] sorted by score, in full-frame coordinates; NO_FACE when empty."""
    detect_cfg = cfg["detect"]
    faces = detector.detect(frame_image, score_min=detect_cfg["score_min"])
    max_faces = detect_cfg.get("max_faces")
    if max_faces:
        faces = faces[:max_faces]
    if not faces:
        return fail(GuidanceCode.NO_FACE, [])
    return ok(faces)
