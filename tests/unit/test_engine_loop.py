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


# --------------------------------------------------------------- the face outline


class _FakeDetector(object):
    """Counts how often it runs, so the throttle can be observed."""

    def __init__(self, faces):
        self.faces = faces
        self.calls = 0

    def detect(self, image, score_min=0.5):
        self.calls += 1
        return list(self.faces)


def _bare_engine(cfg, detector):
    """An Engine without the camera, the models or the database.

    __new__ instead of __init__ on purpose: the two methods under test touch only these
    attributes, and building a real Engine would need five TensorRT engines and a Nano.
    """
    from edgeface.engine.__main__ import Engine

    engine = Engine.__new__(Engine)
    engine.cfg = cfg
    engine.models = {"detector": detector}
    engine.face_box = None
    engine.face_box_good = False
    engine._last_box_detect = None
    engine.publisher = type("P", (), {"preview_period": 0.2})()
    return engine


def test_the_outline_is_stored_as_fractions_of_the_frame(cfg):
    """Fractions, not pixels: the preview is a different size from the frame."""
    engine = _bare_engine(cfg, _FakeDetector([]))
    detection = Detection(bbox=np.array([320.0, 180.0, 640.0, 540.0]), score=0.9, kps=None)
    engine._remember_box(detection, (720, 1280, 3), good=True)
    assert engine.face_box == (0.25, 0.25, 0.5, 0.75)
    assert engine.face_box_good is True


def test_the_outline_disappears_when_the_face_does(cfg):
    engine = _bare_engine(cfg, _FakeDetector([]))
    engine._remember_box(Detection(np.array([0.0, 0.0, 10.0, 10.0]), 0.9, None),
                         (100, 100, 3), good=True)
    engine._remember_box(None, (100, 100, 3), good=False)
    assert engine.face_box is None and engine.face_box_good is False


def test_the_waiting_detector_runs_at_preview_rate_not_camera_rate(cfg):
    """While the nurse decides, the box is refreshed as often as the picture it is drawn
    on - five times a second - not as often as the camera delivers frames."""
    face = Detection(bbox=np.array([10.0, 10.0, 50.0, 50.0]), score=0.9, kps=None)
    detector = _FakeDetector([face])
    engine = _bare_engine(cfg, detector)
    frame = Frame(1, 0.0, np.zeros((480, 640, 3), dtype=np.uint8))

    for tick in range(15):            # one second of camera at 15 fps
        engine._detect_box_only(frame, tick / 15.0)
    assert detector.calls == 5
    assert engine.face_box is not None
    # Never green while waiting: no gate was run on that frame.
    assert engine.face_box_good is False


def test_the_outline_can_be_switched_off(cfg):
    detector = _FakeDetector([Detection(np.array([1.0, 1.0, 9.0, 9.0]), 0.9, None)])
    off = dict(cfg)
    off["kiosk"] = dict(cfg.get("kiosk") or {}, face_box=False)
    engine = _bare_engine(off, detector)
    engine._detect_box_only(Frame(1, 0.0, np.zeros((480, 640, 3), dtype=np.uint8)), 10.0)
    assert detector.calls == 0 and engine.face_box is None
