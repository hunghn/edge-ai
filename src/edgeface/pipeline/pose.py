"""S3 coarse pose (5 keypoints) and S5 fine pose (106 landmarks + solvePnP).

Sign convention, shared by both stages and locked by tests/unit/test_pose_*.py:
  yaw   > 0 : the face turns so the nose moves towards the right of the IMAGE
  pitch > 0 : the face looks up
  roll  > 0 : the head tilts so the nose moves towards the left of the IMAGE
"""
import math

import cv2
import numpy as np

from edgeface.common.timing import timed
from edgeface.pipeline.base import fail, ok
from edgeface.pipeline.landmark_index import POSE_POINTS_2D
from edgeface.types import GuidanceCode

# Generic 3D face model in millimetres, in the order of landmark_index.POSE_POINTS_2D:
# nose tip, chin, left and right eye outer corner, left and right mouth corner. The
# values are the population average used by the OpenCV head-pose examples, with the Y
# axis pointing DOWN so the model shares the image axes: a frontal face then decomposes
# to (0, 0, 0) instead of a 180-degree flip. Being an average, it is good enough to gate
# on tens of degrees, not to report a precise angle.
POSE_MODEL_3D = np.array([
    [0.0, 0.0, 0.0],
    [0.0, 330.0, -65.0],
    [-225.0, -170.0, -135.0],
    [225.0, -170.0, -135.0],
    [-150.0, 150.0, -125.0],
    [150.0, 150.0, -125.0],
], dtype=np.float64)

EPS = 1e-6


def _rotate(points, angle_rad, center):
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float64)
    return (np.asarray(points, dtype=np.float64) - center).dot(rot.T) + center


def coarse_from_kps(kps, k_yaw=None):
    """{'yaw', 'roll', 'nose_offset'} from the 5 SCRFD keypoints.

    roll comes straight from the eye line. yaw is a geometric ratio: how far the nose
    sits from the vertical mid-line of the face, in units of half the inter-ocular
    distance, measured after the roll is removed. Converting that ratio to degrees needs
    the calibration constant k_yaw (D-15); without it yaw is None and S3 gates on roll
    only.
    """
    kps = np.asarray(kps, dtype=np.float64)
    if kps.shape != (5, 2):
        raise ValueError("expected (5, 2) keypoints, got {}".format(kps.shape))
    left_eye, right_eye, nose, mouth_left, mouth_right = kps
    eye_delta = right_eye - left_eye
    iod = float(np.linalg.norm(eye_delta))
    if iod < EPS:
        return None
    roll = math.degrees(math.atan2(eye_delta[1], eye_delta[0]))

    eye_mid = (left_eye + right_eye) / 2.0
    flat = _rotate(kps, -math.radians(roll), eye_mid)
    left_eye, right_eye, nose, mouth_left, mouth_right = flat
    mouth_mid = (mouth_left + mouth_right) / 2.0
    axis_x = (( left_eye[0] + right_eye[0]) / 2.0 + mouth_mid[0]) / 2.0
    offset = (nose[0] - axis_x) / (iod / 2.0)

    yaw = None
    if k_yaw:
        yaw = math.degrees(math.asin(max(-1.0, min(1.0, offset / float(k_yaw)))))
    return {"yaw": yaw, "roll": roll, "nose_offset": offset}


@timed("S3")
def coarse_pose(detection, cfg):
    """S3: reject frames that are clearly not facing the camera, before S4 runs."""
    pose_cfg = cfg["pose_coarse"]
    pose = coarse_from_kps(detection.kps, pose_cfg.get("k_yaw"))
    if pose is None:
        return fail(GuidanceCode.LOOK_STRAIGHT, None)
    if abs(pose["roll"]) > pose_cfg["roll_max_deg"]:
        return fail(GuidanceCode.LOOK_STRAIGHT, pose)
    if pose["yaw"] is not None and abs(pose["yaw"]) > pose_cfg["yaw_max_deg"]:
        return fail(GuidanceCode.LOOK_STRAIGHT, pose)
    return ok(pose)


def camera_matrix(width, height, cfg=None):
    """Intrinsics for solvePnP. Approximated as f = image width unless calibrated (D-10)."""
    camera_cfg = (cfg or {}).get("camera") or {}
    if camera_cfg.get("K"):
        return np.asarray(camera_cfg["K"], dtype=np.float64).reshape(3, 3)
    focal = float(width)
    return np.array([[focal, 0.0, width / 2.0],
                     [0.0, focal, height / 2.0],
                     [0.0, 0.0, 1.0]], dtype=np.float64)


def dist_coeffs(cfg=None):
    camera_cfg = (cfg or {}).get("camera") or {}
    if camera_cfg.get("dist"):
        return np.asarray(camera_cfg["dist"], dtype=np.float64).reshape(-1, 1)
    return np.zeros((4, 1), dtype=np.float64)


def _normalize_angle(deg):
    """Map an Euler angle to [-90, 90]: +170 deg of yaw is -10 deg seen from the front."""
    deg = (deg + 180.0) % 360.0 - 180.0
    if deg > 90.0:
        deg -= 180.0
    elif deg < -90.0:
        deg += 180.0
    return deg


def solve_head_pose(points_2d, image_shape, cfg=None):
    """(rvec, tvec) for the six pose points, or None.

    SOLVEPNP_ITERATIVE alone starts from a planar homography guess and, on a face this
    small in the frame, happily converges to the mirrored solution with the head BEHIND
    the camera (negative tz) and a 180-degree roll. Measured on the fixture images it
    returned tz = -3612 mm. EPNP gives a correct starting point, ITERATIVE then refines
    it, and any solution still behind the camera is rejected.

    SQPNP would be the modern single-shot answer but needs OpenCV >= 4.5; JetPack 4.6
    ships 4.1.1.
    """
    height, width = image_shape[:2]
    matrix, dist = camera_matrix(width, height, cfg), dist_coeffs(cfg)
    points_2d = np.ascontiguousarray(np.asarray(points_2d, dtype=np.float64))
    success, rvec, tvec = cv2.solvePnP(POSE_MODEL_3D, points_2d, matrix, dist,
                                       flags=cv2.SOLVEPNP_EPNP)
    if not success:
        return None
    success, rvec, tvec = cv2.solvePnP(POSE_MODEL_3D, points_2d, matrix, dist,
                                       rvec=rvec, tvec=tvec, useExtrinsicGuess=True,
                                       flags=cv2.SOLVEPNP_ITERATIVE)
    if not success or float(np.asarray(tvec).ravel()[2]) <= 0.0:
        return None
    return rvec, tvec


def fine_from_landmarks(landmarks, image_shape, cfg=None):
    """{'yaw', 'pitch', 'roll'} in degrees via solvePnP, or None when it fails."""
    landmarks = np.asarray(landmarks, dtype=np.float64)
    solution = solve_head_pose(landmarks[list(POSE_POINTS_2D)], image_shape, cfg)
    if solution is None:
        return None
    rotation, _ = cv2.Rodrigues(solution[0])
    pitch, yaw, roll = (float(a) for a in cv2.RQDecomp3x3(rotation)[0][:3])
    result = {"yaw": _normalize_angle(yaw), "pitch": _normalize_angle(pitch),
              "roll": _normalize_angle(roll)}
    if any(math.isnan(v) for v in result.values()):
        return None
    return result


@timed("S5")
def fine_pose(landmarks, image_shape, cfg):
    """S5 (pose half): gate on yaw/pitch/roll from the 106 landmarks."""
    pose = fine_from_landmarks(landmarks, image_shape, cfg)
    if pose is None:
        return fail(GuidanceCode.LOOK_STRAIGHT, None)
    limits = cfg["pose_fine"]
    if (abs(pose["yaw"]) > limits["yaw_max_deg"]
            or abs(pose["pitch"]) > limits["pitch_max_deg"]
            or abs(pose["roll"]) > limits["roll_max_deg"]):
        return fail(GuidanceCode.LOOK_STRAIGHT, pose)
    return ok(pose)
