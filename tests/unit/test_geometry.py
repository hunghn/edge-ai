import numpy as np
import pytest

from edgeface.common import geometry as g


def test_xyxy_xywh_roundtrip():
    box = [10.0, 20.0, 110.0, 70.0]
    assert g.xyxy_to_xywh(box) == [10.0, 20.0, 100.0, 50.0]
    assert g.xywh_to_xyxy(g.xyxy_to_xywh(box)) == box


def test_iou():
    assert g.iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert g.iou([0, 0, 10, 10], [5, 0, 15, 10]) == pytest.approx(50.0 / 150.0)
    assert g.iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_nms_suppresses_overlaps_keeps_score_order():
    boxes = np.array([[0, 0, 100, 100], [2, 2, 102, 102], [200, 200, 260, 260], [1, 1, 99, 99]],
                     dtype=np.float32)
    scores = np.array([0.7, 0.9, 0.8, 0.6], dtype=np.float32)
    assert g.nms(boxes, scores, 0.4) == [1, 2]
    assert g.nms(np.zeros((0, 4)), np.zeros((0,)), 0.4) == []


def test_nms_threshold_is_inclusive_keep():
    # two boxes with IoU (with +1 convention) exactly below/above threshold
    boxes = np.array([[0, 0, 9, 9], [5, 0, 14, 9]], dtype=np.float32)
    scores = np.array([0.9, 0.8], dtype=np.float32)
    ovr = 50.0 / 150.0
    assert g.nms(boxes, scores, ovr + 1e-6) == [0, 1]
    assert g.nms(boxes, scores, ovr - 1e-6) == [0]


def test_roi_and_sizes():
    assert g.point_in_rect((5, 5), [0, 0, 10, 10])
    assert not g.point_in_rect((11, 5), [0, 0, 10, 10])
    assert g.bbox_min_side([0, 0, 120, 110]) == 110
    assert g.expand_bbox([0, 0, 10, 20], 2.0) == [-5.0, -10.0, 15.0, 30.0]
    assert g.clip_bbox([-5, -5, 700, 500], 640, 480) == [0.0, 0.0, 639.0, 479.0]


def _random_similarity(rng):
    angle = rng.uniform(-np.pi, np.pi)
    s = rng.uniform(0.3, 3.0)
    t = rng.uniform(-100, 100, size=2)
    r = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return np.hstack([s * r, t[:, None]])


def test_umeyama_recovers_exact_similarity():
    rng = np.random.RandomState(1)
    for _ in range(20):
        m = _random_similarity(rng)
        src = rng.uniform(0, 200, size=(5, 2))
        dst = g.apply_affine(src, m)
        est = g.umeyama_similarity(src, dst)
        np.testing.assert_allclose(est, m, atol=1e-4)


def test_center_scale_matrix_maps_center_to_middle():
    m = g.center_scale_matrix((300.0, 200.0), 192, 0.5)
    np.testing.assert_allclose(g.apply_affine([[300.0, 200.0]], m), [[96.0, 96.0]], atol=1e-5)
    np.testing.assert_allclose(g.apply_affine([[310.0, 200.0]], m), [[101.0, 96.0]], atol=1e-5)
