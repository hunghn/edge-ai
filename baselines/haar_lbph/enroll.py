# -*- coding: utf-8 -*-
"""Train the LBPH baseline from the same clips the main pipeline is enrolled from.

  python3 baselines/haar_lbph/enroll.py --clips data/enroll/*.mp4 --config configs/baseline.yaml

Each clip is one identity, named after the file (BN001.mp4 -> BN001), which keeps the
baseline's gallery aligned with the main one without a separate label file.
"""
import argparse
import glob
import json
import os
import sys

import cv2

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from baselines.haar_lbph.detector import detector_from_config, face_chip  # noqa: E402
from baselines.haar_lbph.lbph import LBPHRecognizer  # noqa: E402
from edgeface import config as cfg_mod  # noqa: E402


def chips_from_clip(path, detector, chip_size, max_samples, stride):
    """Grayscale chips of the largest face, sampled every `stride` frames."""
    capture = cv2.VideoCapture(path)
    chips, index = [], 0
    try:
        while len(chips) < max_samples:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            if index % stride:
                continue
            box = detector.largest(frame)
            if box is None:
                continue
            chip = face_chip(frame, box, chip_size)
            if chip is not None:
                chips.append(chip)
    finally:
        capture.release()
    return chips, index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "baseline.yaml"))
    ap.add_argument("--clips", nargs="+", required=True,
                    help="one clip per identity; the file name is the label")
    ap.add_argument("--samples", type=int, default=10, help="chips kept per identity")
    ap.add_argument("--stride", type=int, default=5, help="use every Nth frame")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    baseline = cfg["baseline"]
    detector = detector_from_config(cfg)
    model = LBPHRecognizer(radius=baseline["radius"], neighbors=baseline["neighbors"],
                           grid_x=baseline["grid"], grid_y=baseline["grid"],
                           threshold=baseline.get("threshold"))

    paths = []
    for pattern in args.clips:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])

    images, labels, names = [], [], {}
    for label, path in enumerate(paths):
        code = os.path.splitext(os.path.basename(path))[0]
        chips, frames = chips_from_clip(path, detector, baseline["chip_size"],
                                        args.samples, args.stride)
        if not chips:
            print("  {}: no face found in {} frames — skipped".format(code, frames))
            continue
        names[str(label)] = code
        images.extend(chips)
        labels.extend([label] * len(chips))
        print("  {}: {} chips from {} frames".format(code, len(chips), frames))

    if not images:
        print("nothing to train on")
        return 1
    model.train(images, labels)
    out = args.out or os.path.join(REPO, baseline["model_path"])
    directory = os.path.dirname(out)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    model.save(out)
    with open(out + ".labels.json", "w") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)
    print("trained {} identities, {} samples -> {}".format(len(names), len(images), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
