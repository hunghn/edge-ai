"""S6: similarity transform of 5 keypoints to the ArcFace template -> 112x112 crop.

Ported from ims_id_server face_backend/src_recognition/face_align.py::estimate_norm and
norm_crop (mode="arcface"), with skimage replaced by a numpy Umeyama estimate.
"""
import cv2
import numpy as np

from edgeface.common.geometry import umeyama_similarity

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
