"""S3 and S5 pose: signs, gates and the solvePnP failure mode that cost a debugging round."""
import cv2
import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.pipeline import pose
from edgeface.pipeline.landmark_index import POSE_POINTS_2D
from edgeface.types import Detection, GuidanceCode

IMAGE_SHAPE = (720, 1280, 3)


@pytest.fixture
def cfg(repo_root):
    import os
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


def project(rotation_deg=(0.0, 0.0, 0.0), translation=(0.0, 0.0, 1500.0),
            shape=IMAGE_SHAPE):
    """Project the 3D pose model under a known rotation -> the six 2D pose points."""
    rvec = np.deg2rad(np.asarray(rotation_deg, dtype=np.float64))
    rotation, _ = cv2.Rodrigues(rvec)
    points = pose.POSE_MODEL_3D.dot(rotation.T) + np.asarray(translation, dtype=np.float64)
    matrix = pose.camera_matrix(shape[1], shape[0])
    projected = matrix.dot(points.T).T
    return projected[:, :2] / projected[:, 2:3]


def landmarks_from(points_2d):
    """Embed the six pose points into a full (106, 2) array."""
    full = np.zeros((106, 2), dtype=np.float32)
    for slot, index in enumerate(POSE_POINTS_2D):
        full[index] = points_2d[slot]
    return full


def five_kps(pitch=0.0, yaw=0.0, roll=0.0):
    """SCRFD-style keypoints (eyes, nose, mouth corners) under a known rotation."""
    points = project((pitch, yaw, roll))
    nose, _chin, eye_left, eye_right, mouth_left, mouth_right = points
    return np.array([eye_left, eye_right, nose, mouth_left, mouth_right], dtype=np.float32)


# ---------------------------------------------------------------- S5
@pytest.mark.parametrize("angles", [(0, 0, 0), (10, 0, 0), (-10, 0, 0), (0, 12, 0),
                                    (0, -12, 0), (0, 0, 8), (0, 0, -8), (7, -9, 5)])
def test_fine_pose_recovers_known_angles(angles):
    got = pose.fine_from_landmarks(landmarks_from(project(angles)), IMAGE_SHAPE)
    assert got is not None
    assert got["pitch"] == pytest.approx(angles[0], abs=1.0)
    assert got["yaw"] == pytest.approx(angles[1], abs=1.0)
    assert got["roll"] == pytest.approx(angles[2], abs=1.0)


def test_fine_pose_is_stable_when_the_face_is_off_centre():
    """A frontal face near the edge of the frame is still frontal."""
    for dx, dy in ((0, 0), (450, 0), (-450, 220), (0, -260)):
        got = pose.fine_from_landmarks(
            landmarks_from(project((0, 0, 0), (dx, dy, 1500.0))), IMAGE_SHAPE)
        assert abs(got["yaw"]) < 1.5 and abs(got["pitch"]) < 1.5


def test_solve_head_pose_beats_plain_iterative_on_real_landmarks():
    """Regression for the mirrored solvePnP solution.

    On the real fixture landmarks, SOLVEPNP_ITERATIVE on its own converges to the
    mirrored solution: the head ends up BEHIND the camera (tz < 0) and decodes as a
    180-degree roll on an upright portrait. Seeding with EPNP fixes it.
    """
    import os

    goldens = np.load(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "fixtures", "goldens.npz"))
    landmarks = goldens["square/lmk106"]
    shape = (512, 512, 3)
    points = np.ascontiguousarray(landmarks[list(POSE_POINTS_2D)].astype(np.float64))
    matrix = pose.camera_matrix(shape[1], shape[0])

    _, _, bad_tvec = cv2.solvePnP(pose.POSE_MODEL_3D, points, matrix, pose.dist_coeffs(),
                                  flags=cv2.SOLVEPNP_ITERATIVE)
    assert float(np.asarray(bad_tvec).ravel()[2]) < 0        # the failure being guarded

    solution = pose.solve_head_pose(points, shape)
    assert solution is not None
    assert float(np.asarray(solution[1]).ravel()[2]) > 0

    angles = pose.fine_from_landmarks(landmarks, shape)
    assert abs(angles["roll"]) < 10.0 and abs(angles["yaw"]) < 10.0


def test_fine_pose_gate(cfg):
    assert pose.fine_pose(landmarks_from(project((5, 5, 3))), IMAGE_SHAPE, cfg).ok
    for angles in ((20, 0, 0), (0, 20, 0), (0, 0, 15)):
        result = pose.fine_pose(landmarks_from(project(angles)), IMAGE_SHAPE, cfg)
        assert not result.ok and result.reason == GuidanceCode.LOOK_STRAIGHT


def test_normalize_angle_folds_near_180():
    assert pose._normalize_angle(170.0) == pytest.approx(-10.0)
    assert pose._normalize_angle(-175.0) == pytest.approx(5.0)
    assert pose._normalize_angle(-12.0) == pytest.approx(-12.0)


# ---------------------------------------------------------------- S3
def test_coarse_roll_matches_the_eye_line():
    got = pose.coarse_from_kps(five_kps(roll=12.0))
    assert got["roll"] == pytest.approx(12.0, abs=1.5)
    assert pose.coarse_from_kps(five_kps(roll=-12.0))["roll"] == pytest.approx(-12.0, abs=1.5)


def test_coarse_nose_offset_follows_yaw_sign_and_is_monotonic():
    offsets = [pose.coarse_from_kps(five_kps(yaw=deg))["nose_offset"]
               for deg in (-30, -15, 0, 15, 30)]
    assert offsets == sorted(offsets)                   # monotonic in yaw
    assert offsets[0] < 0 < offsets[-1]                 # sign matches the image direction
    assert abs(offsets[2]) < 0.05                       # frontal face sits on the axis


def test_coarse_yaw_is_none_until_k_yaw_is_calibrated(cfg):
    assert cfg["pose_coarse"]["k_yaw"] is None
    got = pose.coarse_from_kps(five_kps(yaw=20.0), k_yaw=None)
    assert got["yaw"] is None
    # the gate then only judges roll, and a 20 degree yaw still passes
    assert pose.coarse_pose(Detection(None, 0.9, five_kps(yaw=20.0)), cfg).ok
    calibrated = pose.coarse_from_kps(five_kps(yaw=20.0), k_yaw=1.0)
    assert calibrated["yaw"] is not None and calibrated["yaw"] > 0


def test_coarse_pose_gate_rejects_a_tilted_head(cfg):
    result = pose.coarse_pose(Detection(None, 0.9, five_kps(roll=35.0)), cfg)
    assert not result.ok and result.reason == GuidanceCode.LOOK_STRAIGHT


def test_coarse_pose_handles_degenerate_keypoints(cfg):
    same = np.zeros((5, 2), dtype=np.float32)
    assert pose.coarse_from_kps(same) is None
    assert not pose.coarse_pose(Detection(None, 0.9, same), cfg).ok


def test_coarse_and_fine_agree_on_roll_sign():
    kps = five_kps(roll=10.0)
    coarse = pose.coarse_from_kps(kps)
    fine = pose.fine_from_landmarks(landmarks_from(project((0, 0, 10.0))), IMAGE_SHAPE)
    assert np.sign(coarse["roll"]) == np.sign(fine["roll"])
