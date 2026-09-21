"""The engine loop: order of stages, early exit, and what reaches the collector.

Stub models keep this a pure-numpy test, so it also runs on the Nano.
"""
import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.engine import loop as engine_loop
from edgeface.pipeline import best_frame as bf
from edgeface.pipeline.landmark_index import POSE_POINTS_2D
from edgeface.types import Detection, Frame, GuidanceCode

SHAPE = (720, 1280, 3)


@pytest.fixture
def cfg(repo_root):
    import os
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    merged = dict(base)
    merged["subject"] = dict(base["subject"], min_side_space="frame", min_side_px=110)
    return merged


def frontal_landmarks():
    """106 landmarks of a frontal face big enough to pass S2."""
    from tests.unit.test_pose import landmarks_from, project

    return landmarks_from(project((0.0, 0.0, 0.0), (0.0, 0.0, 1500.0), SHAPE))


def detection_from(landmarks, score=0.9):
    pose_points = landmarks[list(POSE_POINTS_2D)]
    nose, chin, eye_left, eye_right, mouth_left, mouth_right = pose_points
    x1 = float(eye_left[0] - 60)
    x2 = float(eye_right[0] + 60)
    y1 = float(min(eye_left[1], eye_right[1]) - 80)
    y2 = float(chin[1] + 30)
    kps = np.array([eye_left, eye_right, nose, mouth_left, mouth_right], dtype=np.float32)
    return Detection(np.array([x1, y1, x2, y2], dtype=np.float32), score, kps)


class StubModels(dict):
    """Minimal stand-ins; every call is recorded so the test can assert the order."""

    def __init__(self, landmarks, p_real=0.99, embedding=None):
        super(StubModels, self).__init__()
        self.calls = []
        self.landmarks = landmarks
        detection = detection_from(landmarks)
        outer = self

        class Detector(object):
            def detect(self, image, score_min):
                outer.calls.append("detect")
                return [detection]

        class Landmark(object):
            def predict(self, image, bbox):
                outer.calls.append("landmark")
                return outer.landmarks

        class Spoof(object):
            def predict(self, image, bbox_xywh):
                outer.calls.append("spoof")
                other = (1.0 - p_real) / 2.0
                return np.array([other, p_real, other], dtype=np.float32)

        class Recognizer(object):
            def embed_raw(self, aligned):
                outer.calls.append("embed")
                if embedding is not None:
                    return embedding
                vector = np.zeros(512, dtype=np.float32)
                vector[0] = 20.0
                return vector

        self.update({"detector": Detector(), "landmark": Landmark(),
                     "antispoof_v2": Spoof(), "antispoof_v1se": Spoof(),
                     "recognizer": Recognizer()})


def make_frame(image=None, frame_id=1, ts=1000.0):
    if image is None:
        rng = np.random.RandomState(0)
        image = np.clip(np.full(SHAPE, 128, np.int16)
                        + rng.randint(-60, 61, SHAPE), 0, 255).astype(np.uint8)
    return Frame(frame_id, ts, image)


def test_a_good_frame_runs_every_stage_in_order(cfg):
    models = StubModels(frontal_landmarks())
    collector = engine_loop.new_collector(cfg)
    outcome = engine_loop.process_frame(make_frame(), models, cfg, collector)
    assert outcome.guidance is None and outcome.stage is None
    assert models.calls == ["detect", "spoof", "spoof", "landmark", "embed"]
    assert outcome.obs.embedding is not None and outcome.obs.iqa is not None
    assert collector.count == 1


def test_no_face_stops_at_s1_without_touching_the_gpu(cfg):
    models = StubModels(frontal_landmarks())

    class Empty(object):
        def detect(self, image, score_min):
            models.calls.append("detect")
            return []

    models["detector"] = Empty()
    outcome = engine_loop.process_frame(make_frame(), models, cfg,
                                        engine_loop.new_collector(cfg))
    assert outcome.stage == "S1" and outcome.guidance == GuidanceCode.NO_FACE
    assert models.calls == ["detect"]


def test_a_tilted_head_skips_the_two_antispoof_inferences(cfg):
    """S3 exists to save the 13 ms the two MiniFASNets cost (M2 measurements)."""
    from tests.unit.test_pose import landmarks_from, project

    tilted = landmarks_from(project((0.0, 0.0, 35.0), (0.0, 0.0, 1500.0), SHAPE))
    models = StubModels(tilted)
    outcome = engine_loop.process_frame(make_frame(), models, cfg,
                                        engine_loop.new_collector(cfg))
    assert outcome.stage == "S3" and outcome.guidance == GuidanceCode.LOOK_STRAIGHT
    assert "spoof" not in models.calls


def test_a_spoof_stops_before_the_landmark_model(cfg):
    models = StubModels(frontal_landmarks(), p_real=0.10)
    outcome = engine_loop.process_frame(make_frame(), models, cfg,
                                        engine_loop.new_collector(cfg))
    assert outcome.stage == "S4" and outcome.guidance == GuidanceCode.SPOOF_SUSPECT
    assert "landmark" not in models.calls
    assert outcome.obs.spoof.p_real == pytest.approx(0.10, abs=1e-6)


def test_a_blurred_frame_stops_at_s5(cfg):
    import cv2

    models = StubModels(frontal_landmarks())
    blurred = cv2.GaussianBlur(make_frame().image, (31, 31), 12)
    outcome = engine_loop.process_frame(make_frame(blurred), models, cfg,
                                        engine_loop.new_collector(cfg))
    assert outcome.stage == "S5" and outcome.guidance == GuidanceCode.HOLD_STILL
    assert "embed" not in models.calls


def test_frames_accumulate_until_the_collector_is_ready(cfg):
    models = StubModels(frontal_landmarks())
    collector = engine_loop.new_collector(cfg)
    statuses = []
    for i in range(1, 6):
        outcome = engine_loop.process_frame(make_frame(frame_id=i, ts=1000.0 + i * 0.1),
                                            models, cfg, collector)
        statuses.append(outcome.collector)
    assert statuses[-1] == bf.READY
    assert statuses[:-1] == [bf.COLLECTING] * 4
    status, embeddings, n_good = collector.result(1000.6)
    assert status == bf.READY and len(embeddings) == 5 and n_good == 5


def test_an_invalid_embedding_is_reported_not_collected(cfg):
    models = StubModels(frontal_landmarks(), embedding=np.zeros(512, dtype=np.float32))
    collector = engine_loop.new_collector(cfg)
    outcome = engine_loop.process_frame(make_frame(), models, cfg, collector)
    assert outcome.stage == "S7" and outcome.guidance == GuidanceCode.EMBED_INVALID
    assert collector.count == 0
