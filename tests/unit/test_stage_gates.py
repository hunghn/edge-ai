"""S1, S2, S4, S5(IQA) and S7 gates, with stub models instead of real inference."""
import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.pipeline import antispoof, detect, embed, quality, subject
from edgeface.types import Detection, GuidanceCode


@pytest.fixture
def cfg(repo_root):
    import os
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


def det(x1, y1, x2, y2, score=0.9):
    kps = np.array([[x1 + 10, y1 + 10], [x2 - 10, y1 + 10], [(x1 + x2) / 2, (y1 + y2) / 2],
                    [x1 + 12, y2 - 10], [x2 - 12, y2 - 10]], dtype=np.float32)
    return Detection(np.array([x1, y1, x2, y2], dtype=np.float32), score, kps)


class FakeDetector(object):
    def __init__(self, faces):
        self.faces = faces
        self.score_min = None

    def detect(self, image, score_min):
        self.score_min = score_min
        return list(self.faces)


class FakeSpoofModel(object):
    def __init__(self, probs):
        self.probs = np.asarray(probs, dtype=np.float32)
        self.calls = []

    def predict(self, image, bbox_xywh):
        self.calls.append(list(bbox_xywh))
        return self.probs


class FakeRecognizer(object):
    def __init__(self, vector):
        self.vector = np.asarray(vector, dtype=np.float32)

    def embed_raw(self, aligned):
        return self.vector


# ---------------------------------------------------------------- S1
def test_detect_passes_threshold_and_reports_no_face(cfg):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    detector = FakeDetector([det(100, 100, 300, 340)])
    result = detect.detect(image, detector, cfg)
    assert result.ok and len(result.data) == 1
    assert detector.score_min == cfg["detect"]["score_min"]

    empty = detect.detect(image, FakeDetector([]), cfg)
    assert not empty.ok and empty.reason == GuidanceCode.NO_FACE and empty.data == []


# ---------------------------------------------------------------- S2
def test_subject_prefers_the_largest_face(cfg):
    small, large = det(0, 0, 100, 100), det(400, 200, 700, 560)
    result = subject.choose_subject([small, large], (720, 1280, 3), cfg)
    assert result.ok and np.allclose(result.data.bbox, large.bbox)


def test_subject_asks_to_step_closer_when_the_face_is_small(cfg):
    result = subject.choose_subject([det(600, 300, 700, 400)], (720, 1280, 3), cfg)
    assert not result.ok and result.reason == GuidanceCode.STEP_CLOSER


def test_subject_checks_the_roi_before_the_size(cfg):
    """A big face outside the ROI must be told to move, not ignored for a smaller one."""
    tight = dict(cfg)
    tight["subject"] = dict(cfg["subject"], roi=[0.4, 0.4, 0.6, 0.6])
    big_but_off = det(0, 0, 400, 480)
    inside_small = det(600, 330, 680, 410)
    result = subject.choose_subject([big_but_off, inside_small], (720, 1280, 3), tight)
    assert not result.ok and result.reason == GuidanceCode.MOVE_TO_CENTER


def test_min_side_conversion_between_spaces(cfg):
    frame_cfg = dict(cfg)
    frame_cfg["subject"] = dict(cfg["subject"], min_side_space="frame")
    assert subject.min_side_in_frame(frame_cfg, 1280, 720) == 110.0
    # 'det' space: 110 px of a 640-wide letterbox is 220 px of a 1280-wide frame
    assert subject.min_side_in_frame(cfg, 1280, 720) == pytest.approx(220.0)
    assert subject.min_side_in_frame(cfg, 1920, 1080) == pytest.approx(330.0)


def test_roi_defaults_to_the_whole_frame_while_null(cfg):
    assert cfg["subject"]["roi"] is None
    assert subject.roi_rect(cfg, 1280, 720) == [0.0, 0.0, 1279.0, 719.0]


# ---------------------------------------------------------------- S4
def test_antispoof_fuses_both_models_and_uses_xywh(cfg):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    models = {"antispoof_v2": FakeSpoofModel([0.02, 0.96, 0.02]),
              "antispoof_v1se": FakeSpoofModel([0.10, 0.88, 0.02])}
    result = antispoof.check_real(image, det(400, 200, 700, 560), models, cfg)
    assert result.ok
    assert result.data.p_real == pytest.approx((0.96 + 0.88) / 2, abs=1e-6)
    assert result.data.label == 1
    # CropImage takes [x, y, w, h]
    assert models["antispoof_v2"].calls[0] == [400.0, 200.0, 300.0, 360.0]


def test_antispoof_rejects_below_the_threshold(cfg):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    models = {"antispoof_v2": FakeSpoofModel([0.10, 0.84, 0.06]),
              "antispoof_v1se": FakeSpoofModel([0.10, 0.84, 0.06])}
    result = antispoof.check_real(image, det(400, 200, 700, 560), models, cfg)
    assert not result.ok and result.reason == GuidanceCode.SPOOF_SUSPECT
    assert result.data.p_real == pytest.approx(0.84)


def test_antispoof_flags_a_replay_class(cfg):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    models = {"antispoof_v2": FakeSpoofModel([0.05, 0.35, 0.60]),
              "antispoof_v1se": FakeSpoofModel([0.05, 0.35, 0.60])}
    result = antispoof.check_real(image, det(400, 200, 700, 560), models, cfg)
    assert not result.ok and result.data.label == 2


def test_antispoof_reports_a_useless_bbox_instead_of_an_alarm(cfg):
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    models = {"antispoof_v2": FakeSpoofModel([0, 1, 0]),
              "antispoof_v1se": FakeSpoofModel([0, 1, 0])}
    result = antispoof.check_real(image, det(400, 200, 400.5, 200.5), models, cfg)
    assert not result.ok and result.reason == GuidanceCode.INVALID_BBOX


# ---------------------------------------------------------------- S5 (IQA)
def _textured(value=128, noise=60, seed=0):
    rng = np.random.RandomState(seed)
    base = np.full((720, 1280, 3), value, dtype=np.int16)
    base += rng.randint(-noise, noise + 1, size=base.shape)
    return np.clip(base, 0, 255).astype(np.uint8)


def test_quality_accepts_a_sharp_well_lit_face(cfg):
    result = quality.image_quality(_textured(), [400, 200, 700, 560], cfg)
    assert result.ok and result.data["blur"] >= cfg["iqa"]["blur_min"]


def test_quality_reports_darkness_before_blur(cfg):
    import cv2
    dark = cv2.GaussianBlur(_textured(value=20, noise=10), (9, 9), 4)
    result = quality.image_quality(dark, [400, 200, 700, 560], cfg)
    assert not result.ok and result.reason == GuidanceCode.TOO_DARK


def test_quality_reports_blur_and_brightness(cfg):
    import cv2
    blurred = cv2.GaussianBlur(_textured(), (21, 21), 9)
    result = quality.image_quality(blurred, [400, 200, 700, 560], cfg)
    assert not result.ok and result.reason == GuidanceCode.HOLD_STILL

    bright = quality.image_quality(_textured(value=240, noise=8), [400, 200, 700, 560], cfg)
    assert not bright.ok and bright.reason == GuidanceCode.TOO_BRIGHT


def test_quality_measures_a_fixed_size_patch(cfg):
    """Same face, different pixel sizes: the measurement must not depend on the crop size."""
    image = _textured()
    small = quality.measure(image, [400, 200, 500, 300], size=112)
    large = quality.measure(image, [400, 200, 900, 700], size=112)
    assert small is not None and large is not None
    assert quality.face_patch(image, [400, 200, 900, 700]).shape == (112, 112)


# ---------------------------------------------------------------- S7
def test_embed_normalizes_and_keeps_the_raw_norm():
    aligned = np.zeros((112, 112, 3), dtype=np.uint8)
    result = embed.embed(aligned, FakeRecognizer(np.arange(512, dtype=np.float32)), 7, 1.5)
    assert result.ok
    assert float(np.linalg.norm(result.data.vector)) == pytest.approx(1.0, abs=1e-6)
    assert result.data.raw_norm > 0 and result.data.frame_id == 7


def test_embed_rejects_nan_and_zero_vectors():
    aligned = np.zeros((112, 112, 3), dtype=np.uint8)
    nan_vec = np.full(512, np.nan, dtype=np.float32)
    assert embed.embed(aligned, FakeRecognizer(nan_vec)).reason == GuidanceCode.EMBED_INVALID
    zero = np.zeros(512, dtype=np.float32)
    assert embed.embed(aligned, FakeRecognizer(zero)).reason == GuidanceCode.EMBED_INVALID
