"""S4: fuse MiniFASNetV2 (crop 2.7) and MiniFASNetV1SE (crop 4.0).

Ported from ims_id_server tools/tools.py::check_real_face(mode="both"): the two softmax
outputs are summed and divided by 2, and index 1 is "real". The reference then flips the
label below 0.65; this project gates directly on the spec's p_real >= 0.85 instead.
"""
import numpy as np

from edgeface.common.geometry import xyxy_to_xywh
from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import GuidanceCode, SpoofScore

REAL_CLASS = 1


def fuse(probs_list, mode="mean"):
    """Mean of the per-model softmax vectors (D-05)."""
    stacked = np.vstack([np.asarray(p, dtype=np.float64).reshape(-1) for p in probs_list])
    if mode == "mean":
        return (stacked.sum(axis=0) / stacked.shape[0]).astype(np.float32)
    if mode == "sum":
        return stacked.sum(axis=0).astype(np.float32)
    raise ValueError("unknown antispoof fusion mode: {}".format(mode))


@timed("S4")
def check_real(image, detection, models, cfg):
    """models: {"antispoof_v2": MiniFASNet, "antispoof_v1se": MiniFASNet}."""
    spoof_cfg = cfg["antispoof"]
    bbox_xywh = xyxy_to_xywh(detection.bbox)
    if bbox_xywh[2] < 1.0 or bbox_xywh[3] < 1.0:
        # Not a spoof, just a useless box: do not raise a false alarm on the kiosk.
        return fail(GuidanceCode.INVALID_BBOX, None)

    per_model = {}
    for crop in spoof_cfg["crops"]:
        name = crop["model"]
        per_model[name] = models[name].predict(image, bbox_xywh)
    fused = fuse(list(per_model.values()), spoof_cfg.get("fusion", "mean"))
    real_index = spoof_cfg.get("real_class_index", REAL_CLASS)
    score = SpoofScore(p_real=float(fused[real_index]), probs=fused,
                       label=int(np.argmax(fused)), per_model=per_model)
    if score.label != real_index or score.p_real < spoof_cfg["p_real_min"]:
        return fail(GuidanceCode.SPOOF_SUSPECT, score)
    return ok(score)
