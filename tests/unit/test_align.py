import numpy as np

from edgeface.common.geometry import apply_affine
from edgeface.pipeline.align import ARCFACE_SRC, estimate_norm, norm_crop


def test_template_maps_to_itself():
    np.testing.assert_allclose(estimate_norm(ARCFACE_SRC), [[1, 0, 0], [0, 1, 0]], atol=1e-5)


def test_rotated_scaled_keypoints_land_on_template():
    angle = np.deg2rad(20.0)
    r = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    kps = ARCFACE_SRC.dot(r.T) * 2.5 + np.array([400.0, 250.0])
    m = estimate_norm(kps)
    np.testing.assert_allclose(apply_affine(kps, m), ARCFACE_SRC, atol=1e-3)


def test_norm_crop_shape_and_content():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    kps = ARCFACE_SRC * 2.0 + np.array([200.0, 100.0])
    x, y = int(round(kps[2, 0])), int(round(kps[2, 1]))
    img[y - 3:y + 4, x - 3:x + 4] = 255  # bright patch on the nose point
    crop = norm_crop(img, kps)
    assert crop.shape == (112, 112, 3)
    nx, ny = int(round(ARCFACE_SRC[2, 0])), int(round(ARCFACE_SRC[2, 1]))
    assert crop[ny, nx].min() > 200
