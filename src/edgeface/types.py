"""Shared value types. namedtuples only: the device runs Python 3.6 (no dataclasses)."""
import enum
from collections import namedtuple

# frame_id: monotonically increasing int; ts: time.monotonic() at capture; image: HxWx3 uint8 BGR
Frame = namedtuple("Frame", ["frame_id", "ts", "image"])

# bbox: (4,) float32 [x1, y1, x2, y2] in frame pixels; score: float; kps: (5, 2) float32 or None
Detection = namedtuple("Detection", ["bbox", "score", "kps"])

# Uniform return shape of every pipeline stage. reason is None when ok.
StageResult = namedtuple("StageResult", ["ok", "reason", "data"])

# vector: (512,) float32, L2-normalized; quality: float or None
Embedding = namedtuple("Embedding", ["frame_id", "ts", "vector", "quality"])


class Decision(enum.Enum):
    # Only the outcomes named in the spec. The remaining values depend on the
    # §6.3 rule engine, which has not been decided yet.
    SPOOF_SUSPECT = "spoof_suspect"
    LOW_QUALITY = "low_quality"
    REVIEW_REQUIRED = "review_required"
