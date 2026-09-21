"""S7: ArcFace embedding of the aligned crop."""
import numpy as np

from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import Embedding, GuidanceCode


@timed("S7")
def embed(aligned_bgr, recognizer, frame_id=None, ts=None):
    """Embedding with an L2-normalized (512,) vector; raw_norm keeps the original length.

    FP16 engines can produce NaN or a zero vector on a degenerate crop, and a zero
    vector would match everything after normalization, so both are rejected here.
    """
    raw = recognizer.embed_raw(aligned_bgr)
    norm = float(np.linalg.norm(raw))
    if not np.isfinite(raw).all() or norm < 1e-6:
        return fail(GuidanceCode.EMBED_INVALID, None)
    vector = (raw / norm).astype(np.float32)
    return ok(Embedding(frame_id=frame_id, ts=ts, vector=vector, quality=None, raw_norm=norm))
