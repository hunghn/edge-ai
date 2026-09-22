# -*- coding: utf-8 -*-
"""Generate labelled synthetic clips, so the tooling can be exercised without real people.

  python tools/dataset/make_synthetic_clips.py --out data/synthetic --identities 3

These are NOT a substitute for the dataset of M8: the faces are one public-domain photo
warped per identity, which is enough to prove the scripts run end to end and nothing more.
Accuracy numbers from synthetic clips mean nothing and must never reach the report.
"""
import argparse
import os
import sys

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FIXTURE = os.path.join(REPO, "tests", "fixtures", "astronaut.jpg")


def identity_face(source, index):
    """A deterministic per-identity variation: slight scale, tint and gamma."""
    rng = np.random.RandomState(1000 + index)
    scale = 1.0 + rng.uniform(-0.08, 0.08)
    face = cv2.resize(source, None, fx=scale, fy=scale)
    tint = rng.uniform(0.85, 1.15, size=3)
    face = np.clip(face.astype(np.float32) * tint, 0, 255).astype(np.uint8)
    gamma = rng.uniform(0.85, 1.2)
    table = np.clip(((np.arange(256) / 255.0) ** gamma) * 255.0, 0, 255).astype(np.uint8)
    return cv2.LUT(face, table)


def write_clip(path, face, frames=45, size=(1280, 720), seed=0, blur_frames=()):
    rng = np.random.RandomState(seed)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 15.0, size)
    height, width = size[1], size[0]
    for i in range(frames):
        canvas = np.full((height, width, 3), 40, dtype=np.uint8)
        # The fixture is a head-and-shoulders portrait, so the head sits in the top
        # third: anchor near y = -120 and the head lands inside the frame at this zoom.
        # The face must stay above subject.min_side_px (110 px in detector space = 220 px
        # in a 1280-wide frame), or S2 rejects every frame with "step closer".
        zoom = 3.4 + 0.15 * np.sin(i / 9.0 + seed)
        scaled = cv2.resize(face, None, fx=zoom, fy=zoom)
        fh, fw = scaled.shape[:2]
        x = int(width / 2 - fw / 2 + 25 * np.sin(i / 7.0 + seed))
        y = -180
        sx, sy = max(0, x), max(0, y)
        fx, fy = sx - x, sy - y
        x2, y2 = min(width, x + fw), min(height, y + fh)
        canvas[sy:y2, sx:x2] = scaled[fy:fy + (y2 - sy), fx:fx + (x2 - sx)]
        canvas = np.clip(canvas.astype(np.int16)
                         + rng.randint(-6, 7, size=canvas.shape), 0, 255).astype(np.uint8)
        if i in blur_frames:
            canvas = cv2.GaussianBlur(canvas, (15, 15), 6)
        writer.write(canvas)
    writer.release()
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "data", "synthetic"))
    ap.add_argument("--identities", type=int, default=3)
    ap.add_argument("--frames", type=int, default=45)
    args = ap.parse_args()

    source = cv2.imread(FIXTURE)
    if source is None:
        raise SystemExit("missing fixture " + FIXTURE)
    for directory in ("enroll", "probe"):
        path = os.path.join(args.out, directory)
        if not os.path.isdir(path):
            os.makedirs(path)

    for index in range(args.identities):
        code = "BN{:03d}".format(index + 1)
        face = identity_face(source, index)
        write_clip(os.path.join(args.out, "enroll", code + ".mp4"), face,
                   frames=args.frames, seed=index)
        # The probe clip is the same identity filmed again: a different seed moves the
        # face around and adds a few blurred frames, like someone stepping up twice.
        write_clip(os.path.join(args.out, "probe", code + ".mp4"), face,
                   frames=args.frames, seed=index + 50, blur_frames=(12, 13, 14))
        print("wrote", code)
    print("clips in", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
