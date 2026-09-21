"""S6: similarity transform of 5 keypoints to the ArcFace template -> 112x112 crop.

Ported from ims_id_server face_backend/src_recognition/face_align.py::estimate_norm and
norm_crop (mode="arcface"), with skimage replaced by a numpy Umeyama estimate.
"""
import cv2
import numpy as np

from edgeface.common.geometry import umeyama_similarity
from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.types import GuidanceCode

ARCFACE_SRC = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def estimate_norm(kps, image_size=112):
    kps = np.asarray(kps, dtype=np.float32)
    if kps.shape != (5, 2):
        raise ValueError("expected (5, 2) keypoints, got {}".format(kps.shape))
    return umeyama_similarity(kps, ARCFACE_SRC * (float(image_size) / 112.0))


def norm_crop(img, kps, image_size=112):
    """img: HxWx3 uint8 BGR; kps: (5, 2) left eye, right eye, nose, left mouth, right mouth.

    Returns image_size x image_size BGR crop (ArcFace wrapper converts to RGB).
    """
    m = estimate_norm(kps, image_size)
    return cv2.warpAffine(img, m, (image_size, image_size), borderValue=0.0)


def residual_px(kps, matrix, image_size=112):
    """Mean distance (px) between the transformed keypoints and the template.

    A large residual means the five points are not arranged like a face at all, which is
    a cheap sanity check on top of the gates.
    """
    from edgeface.common.geometry import apply_affine

    template = ARCFACE_SRC * (float(image_size) / 112.0)
    moved = apply_affine(np.asarray(kps, dtype=np.float32), matrix)
    return float(np.mean(np.linalg.norm(moved - template, axis=1)))


def five_points_from(detection, landmarks, source):
    """The five alignment points, from SCRFD keypoints or from the 106 landmarks (D-09)."""
    if source == "scrfd":
        if detection.kps is None:
            raise ValueError("align.kps_source is 'scrfd' but the detection has no keypoints")
        return np.asarray(detection.kps, dtype=np.float32)
    if source == "lmk106":
        if landmarks is None:
            raise ValueError("align.kps_source is 'lmk106' but S5 did not run")
        from edgeface.pipeline.landmark_index import five_points

        return five_points(landmarks)
    raise ValueError("unknown align.kps_source: {}".format(source))


@timed("S6")
def align(image, detection, landmarks, cfg):
    """S6: 112x112 BGR crop aligned to the ArcFace template."""
    align_cfg = cfg.get("align") or {}
    image_size = int(align_cfg.get("image_size", 112))
    try:
        kps = five_points_from(detection, landmarks, align_cfg.get("kps_source", "scrfd"))
        matrix = estimate_norm(kps, image_size)
    except ValueError:
        return fail(GuidanceCode.LOOK_STRAIGHT, None)

    max_residual = align_cfg.get("max_residual_px")
    if max_residual is not None and residual_px(kps, matrix, image_size) > max_residual:
        return fail(GuidanceCode.LOOK_STRAIGHT, None)
    warped = cv2.warpAffine(image, matrix, (image_size, image_size), borderValue=0.0)
    return ok(warped)
