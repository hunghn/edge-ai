"""Derive (and draw) the 106-landmark index map, instead of trusting the reference repo.

  python tools/viz/landmark_index.py [--out docs/figures/lmk106_index.png]

It prints the mapping derived from data — nearest landmark to each SCRFD keypoint, the
extreme points of each group — and renders a numbered overlay to check by eye. The
result is recorded in src/edgeface/pipeline/landmark_index.py.
"""
import argparse
import os
import sys

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface.pipeline import landmark_index as index  # noqa: E402

GOLDENS = os.path.join(REPO, "tests", "fixtures", "goldens.npz")
FIXTURE = os.path.join(REPO, "tests", "fixtures", "astronaut.jpg")
KEYPOINT_NAMES = ("left eye", "right eye", "nose", "mouth left", "mouth right")


def derive(goldens, name):
    landmarks, keypoints = goldens[name + "/lmk106"], goldens[name + "/kps"][0]
    print("== {}".format(name))
    for label, keypoint in zip(KEYPOINT_NAMES, keypoints):
        distances = np.linalg.norm(landmarks - keypoint, axis=1)
        nearest = np.argsort(distances)[:3]
        print("   {:11s} nearest landmarks {} at {} px".format(
            label, list(nearest), np.round(distances[nearest], 1)))
    groups = {"left eye": index.LEFT_EYE, "right eye": index.RIGHT_EYE,
              "mouth": index.MOUTH, "contour": index.CONTOUR, "nose": index.NOSE}
    for label, group in groups.items():
        points = landmarks[list(group)]
        print("   {:11s} xmin={} xmax={} ymin={} ymax={}".format(
            label, group[int(np.argmin(points[:, 0]))], group[int(np.argmax(points[:, 0]))],
            group[int(np.argmin(points[:, 1]))], group[int(np.argmax(points[:, 1]))]))
    return landmarks


def check_recorded_map(landmarks):
    """The recorded constants must still be the extremes we derived."""
    problems = []
    checks = [
        (index.CHIN, index.CONTOUR, "ymax", "chin"),
        (index.LEFT_EYE_OUTER, index.LEFT_EYE, "xmin", "left eye outer"),
        (index.RIGHT_EYE_OUTER, index.RIGHT_EYE, "xmax", "right eye outer"),
        (index.MOUTH_LEFT, index.MOUTH, "xmin", "mouth left"),
        (index.MOUTH_RIGHT, index.MOUTH, "xmax", "mouth right"),
    ]
    for recorded, group, kind, label in checks:
        points = landmarks[list(group)]
        axis, pick = (1, np.argmax) if kind == "ymax" else (0, np.argmin if kind == "xmin"
                                                            else np.argmax)
        expected = group[int(pick(points[:, axis]))]
        if expected != recorded:
            problems.append("{}: recorded {}, data says {}".format(label, recorded, expected))
    return problems


def draw(image, landmarks, out_path):
    canvas = cv2.resize(image, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    for i, (x, y) in enumerate(landmarks * 3.0):
        highlight = i in index.POSE_POINTS_2D
        color = (0, 0, 255) if highlight else (0, 200, 0)
        cv2.circle(canvas, (int(x), int(y)), 3 if highlight else 2, color, -1)
        cv2.putText(canvas, str(i), (int(x) + 3, int(y) - 3), cv2.FONT_HERSHEY_SIMPLEX,
                    0.32, color, 1, cv2.LINE_AA)
    if not os.path.isdir(os.path.dirname(out_path)):
        os.makedirs(os.path.dirname(out_path))
    cv2.imwrite(out_path, canvas)
    print("wrote", out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "figures", "lmk106_index.png"))
    args = ap.parse_args()
    goldens = dict(np.load(GOLDENS))

    problems = []
    for name in ("square", "wide"):
        landmarks = derive(goldens, name)
        problems.extend("{}: {}".format(name, p) for p in check_recorded_map(landmarks))
    if problems:
        print("\nMISMATCH with src/edgeface/pipeline/landmark_index.py:")
        for problem in problems:
            print("  -", problem)
        return 1
    print("\nrecorded index map agrees with the data on both fixtures")
    draw(cv2.imread(FIXTURE), goldens["square/lmk106"], args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
