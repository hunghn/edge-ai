"""Index map of the 106 landmarks produced by 2d106det.

These indices are NOT taken on trust from the reference repo: tools/viz/landmark_index.py
derives them from data and this module records the result. The derivation, run on both
fixture images (tests/fixtures/goldens.npz), is:

  * eye / nose / mouth groups: nearest landmark to each SCRFD keypoint
  * eye and mouth corners: extreme x inside the respective group
  * chin: largest y over the face contour

Both images agree, which is what makes the map trustworthy. Re-run the tool after any
change of landmark model.
"""

# Contiguous groups.
CONTOUR = tuple(range(0, 33))        # jaw line, index 0 is the chin
LEFT_EYE = tuple(range(33, 43))      # left on the IMAGE (the subject's right eye)
MOUTH = tuple(range(52, 72))
NOSE = tuple(range(72, 87))
RIGHT_EYE = tuple(range(87, 97))

# Single points.
CHIN = 0
NOSE_TIP = 86
LEFT_EYE_OUTER = 35
LEFT_EYE_INNER = 39
RIGHT_EYE_INNER = 89
RIGHT_EYE_OUTER = 93
MOUTH_LEFT = 52
MOUTH_RIGHT = 61

# The six points used for solvePnP in S5, in the order of POSE_MODEL_3D (pose.py).
POSE_POINTS_2D = (NOSE_TIP, CHIN, LEFT_EYE_OUTER, RIGHT_EYE_OUTER, MOUTH_LEFT, MOUTH_RIGHT)


def eye_centers(landmarks):
    """(left_center, right_center) as the mean of each eye contour."""
    return (landmarks[list(LEFT_EYE)].mean(axis=0), landmarks[list(RIGHT_EYE)].mean(axis=0))


def five_points(landmarks):
    """The 5-point set ArcFace alignment expects, derived from the 106 landmarks.

    Order matches SCRFD keypoints: left eye, right eye, nose tip, left mouth, right mouth.
    """
    import numpy as np

    left_eye, right_eye = eye_centers(landmarks)
    return np.array([left_eye, right_eye, landmarks[NOSE_TIP],
                     landmarks[MOUTH_LEFT], landmarks[MOUTH_RIGHT]], dtype=np.float32)
