import numpy as np
import pytest

from edgeface.common.imgproc import letterbox, to_blob
from edgeface.models import scrfd
from edgeface.runtime.base import Backend, TensorSpec

STRIDES = (8, 16, 32)


def _empty_outputs(size=640, batched=False):
    outs = []
    for last in (1, 4, 10):
        for s in STRIDES:
            n = (size // s) ** 2 * 2
            shape = (1, n, last) if batched else (n, last)
            outs.append(np.zeros(shape, dtype=np.float32))
    return outs


class _FakeBackend(Backend):
    def __init__(self, outputs):
        super(_FakeBackend, self).__init__("fake")
        self._outs = outputs

    @property
    def inputs(self):
        return [TensorSpec("input.1", (1, 3, 640, 640), np.float32)]

    @property
    def outputs(self):
        return []

    def infer(self, feeds):
        assert feeds["input.1"].shape == (1, 3, 640, 640)
        from collections import OrderedDict
        return OrderedDict((str(i), o) for i, o in enumerate(self._outs))


def test_anchor_centers_layout():
    c = scrfd.anchor_centers(2, 3, 8, 2)
    # row-major over (y, x), each location repeated num_anchors times, (x, y) order
    expected = [[0, 0], [0, 0], [8, 0], [8, 0], [16, 0], [16, 0],
                [0, 8], [0, 8], [8, 8], [8, 8], [16, 8], [16, 8]]
    np.testing.assert_array_equal(c, expected)


def _plant(outs, stride, index, score, ltrb, kps_offsets):
    si = STRIDES.index(stride)
    outs[si][index, 0] = score
    outs[3 + si][index] = np.asarray(ltrb, dtype=np.float32) / stride
    outs[6 + si][index] = np.asarray(kps_offsets, dtype=np.float32).reshape(-1) / stride


def test_decode_single_face_with_letterbox_scale():
    outs = _empty_outputs()
    # stride 16, grid 40x40, anchor index for (row 10, col 20), anchor 1
    idx = (10 * 40 + 20) * 2 + 1
    cx, cy = 20 * 16, 10 * 16
    kps = [[-10, -5], [10, -5], [0, 0], [-8, 10], [8, 10]]
    _plant(outs, 16, idx, 0.9, [30, 40, 30, 50], kps)
    det = scrfd.SCRFD(_FakeBackend(outs))
    faces = det.postprocess(outs, scale=0.5, score_min=0.6)
    assert len(faces) == 1
    f = faces[0]
    assert f.score == pytest.approx(0.9)
    np.testing.assert_allclose(f.bbox, np.array([cx - 30, cy - 40, cx + 30, cy + 50]) / 0.5, atol=1e-3)
    np.testing.assert_allclose(f.kps, (np.array([[cx, cy]]) + kps) / 0.5, atol=1e-3)


def test_score_gate_and_nms():
    outs = _empty_outputs()
    base = (5 * 80 + 5) * 2
    _plant(outs, 8, base, 0.95, [20, 20, 20, 20], [[0, 0]] * 5)
    _plant(outs, 8, base + 1, 0.85, [21, 20, 20, 20], [[0, 0]] * 5)   # duplicate -> NMS
    _plant(outs, 32, 3, 0.55, [10, 10, 10, 10], [[0, 0]] * 5)         # below gate
    det = scrfd.SCRFD(_FakeBackend(outs))
    faces = det.postprocess(outs, scale=1.0, score_min=0.6)
    assert [round(f.score, 2) for f in faces] == [0.95]
    assert det.postprocess(_empty_outputs(), 1.0, 0.6) == []


def test_output_grouping_is_order_and_batch_independent():
    outs = _empty_outputs(batched=True)
    idx = 7
    outs[2][0, idx, 0] = 0.8  # stride 32 score
    outs[5][0, idx] = [1, 1, 1, 1]
    shuffled = [outs[i] for i in (8, 2, 5, 0, 3, 6, 1, 4, 7)]
    det = scrfd.SCRFD(_FakeBackend(shuffled))
    faces = det.postprocess(shuffled, 1.0, 0.6)
    assert len(faces) == 1 and faces[0].score == pytest.approx(0.8)


def test_letterbox_16x9():
    img = np.full((1080, 1920, 3), 255, dtype=np.uint8)
    out, scale = letterbox(img, (640, 640))
    assert out.shape == (640, 640, 3)
    assert scale == pytest.approx(360.0 / 1080.0)
    assert out[359, 639, 0] == 255 and out[360, 0, 0] == 0


def test_to_blob_matches_swap_and_normalization():
    img = np.zeros((2, 2, 3), dtype=np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = 10, 20, 30  # B, G, R
    blob = to_blob(img, 127.5, 128.0, swap_rb=True)
    assert blob.shape == (1, 3, 2, 2) and blob.dtype == np.float32
    np.testing.assert_allclose(blob[0, :, 0, 0], (np.array([30, 20, 10]) - 127.5) / 128.0)
    raw = to_blob(img, 0.0, 1.0, swap_rb=False)
    np.testing.assert_allclose(raw[0, :, 0, 0], [10, 20, 30])


def test_detect_end_to_end_with_fake_backend():
    outs = _empty_outputs()
    _plant(outs, 32, 0, 0.7, [5, 5, 5, 5], [[0, 0]] * 5)
    det = scrfd.SCRFD(_FakeBackend(outs))
    faces = det.detect(np.zeros((1080, 1920, 3), dtype=np.uint8), score_min=0.6)
    assert len(faces) == 1
    np.testing.assert_allclose(faces[0].bbox, np.array([-5, -5, 5, 5]) * 3.0, atol=1e-3)


def test_to_blob_backends_agree():
    """cv2.dnn.blobFromImage (fast path) vs the numpy fallback.

    blobFromImage multiplies by 1/std where the numpy version divides by std, so for a
    std that is not a power of two (ArcFace uses 127.5) the two differ by one ulp.
    """
    from edgeface.common.imgproc import _to_blob_numpy
    rng = np.random.RandomState(0)
    img = rng.randint(0, 256, size=(64, 48, 3)).astype(np.uint8)
    for mean, std, swap in ((127.5, 128.0, True), (0.0, 1.0, False)):
        np.testing.assert_array_equal(
            to_blob(img, mean, std, swap), _to_blob_numpy(img, mean, std, swap),
            err_msg="std is a power of two: the two paths must match exactly")
    np.testing.assert_allclose(
        to_blob(img, 127.5, 127.5, True), _to_blob_numpy(img, 127.5, 127.5, True),
        rtol=1e-6, atol=1e-6)
