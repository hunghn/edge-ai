"""Shared value types. namedtuples only: the device runs Python 3.6 (no dataclasses)."""
import enum
from collections import namedtuple

# frame_id: monotonically increasing int; ts: time.monotonic() at capture; image: HxWx3 uint8 BGR
Frame = namedtuple("Frame", ["frame_id", "ts", "image"])

# bbox: (4,) float32 [x1, y1, x2, y2] in frame pixels; score: float; kps: (5, 2) float32 or None
Detection = namedtuple("Detection", ["bbox", "score", "kps"])

# Uniform return shape of every pipeline stage. reason is None when ok.
StageResult = namedtuple("StageResult", ["ok", "reason", "data"])

# vector: (512,) float32, L2-normalized; quality: filled in by S8;
# raw_norm: L2 norm before normalization, a candidate quality signal (S8 option C)
Embedding = namedtuple("Embedding", ["frame_id", "ts", "vector", "quality", "raw_norm"])
Embedding.__new__.__defaults__ = (None, None)


class Decision(enum.Enum):
    # Only the outcomes named in the spec. The remaining values depend on the
    # §6.3 rule engine, which has not been decided yet.
    SPOOF_SUSPECT = "spoof_suspect"
    LOW_QUALITY = "low_quality"
    REVIEW_REQUIRED = "review_required"


class GuidanceCode(object):
    """Reasons a stage rejected a frame. The kiosk maps these to Vietnamese text."""
    NO_FACE = "NO_FACE"
    STEP_CLOSER = "STEP_CLOSER"
    MOVE_TO_CENTER = "MOVE_TO_CENTER"
    LOOK_STRAIGHT = "LOOK_STRAIGHT"
    HOLD_STILL = "HOLD_STILL"
    TOO_DARK = "TOO_DARK"
    TOO_BRIGHT = "TOO_BRIGHT"
    SPOOF_SUSPECT = "SPOOF_SUSPECT"
    INVALID_BBOX = "INVALID_BBOX"
    EMBED_INVALID = "EMBED_INVALID"
    CAMERA_ERROR = "CAMERA_ERROR"


# One face as it travels through S1-S8. Fields are filled in stage by stage and stay
# None when their stage did not run (an earlier gate failed).
FaceObs = namedtuple("FaceObs", [
    "frame_id", "ts", "det",          # S1: Detection
    "pose_coarse",                    # S3: {"yaw", "roll"}
    "spoof",                          # S4: SpoofScore
    "lmk106", "pose_fine", "iqa",     # S5: (106,2), {"yaw","pitch","roll"}, {"blur","lum"}
    "aligned",                        # S6: 112x112 BGR
    "embedding",                      # S7: Embedding
    "quality",                        # S8: float or None
])
FaceObs.__new__.__defaults__ = (None,) * (len(FaceObs._fields) - 3)

# S4 output: fused probabilities plus each model's own, for later analysis.
SpoofScore = namedtuple("SpoofScore", ["p_real", "probs", "label", "per_model"])
