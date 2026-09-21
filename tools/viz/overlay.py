"""Draw what the pipeline sees onto a video, to debug gates by eye.

  python tools/viz/overlay.py --video clip.mp4 --out clip_overlay.mp4 [--config ...]

Green box = the frame passed every gate, orange = it was rejected, with the reason and
the numbers that caused it printed on the frame.
"""
import argparse
import os
import sys

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.engine import loop as engine_loop  # noqa: E402
from edgeface.engine.models import close_models, load_models  # noqa: E402
from edgeface.pipeline.capture import FileSource  # noqa: E402
from edgeface.pipeline.subject import roi_rect  # noqa: E402
from edgeface.types import Frame  # noqa: E402

PASS = (0, 220, 0)
REJECT = (0, 140, 255)
INFO = (240, 240, 240)


def annotate(image, outcome, cfg):
    obs = outcome.obs
    color = PASS if outcome.guidance is None else REJECT
    height, width = image.shape[:2]

    roi = [int(v) for v in roi_rect(cfg, width, height)]
    cv2.rectangle(image, (roi[0], roi[1]), (roi[2], roi[3]), (120, 120, 120), 1)

    if obs.det is not None:
        x1, y1, x2, y2 = (int(v) for v in obs.det.bbox)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        if obs.det.kps is not None:
            for x, y in obs.det.kps:
                cv2.circle(image, (int(x), int(y)), 3, (255, 200, 0), -1)
    if obs.lmk106 is not None:
        for x, y in obs.lmk106:
            cv2.circle(image, (int(x), int(y)), 1, (0, 255, 255), -1)

    lines = ["frame {} {}".format(obs.frame_id,
                                  outcome.guidance or "PASS ({})".format(outcome.collector))]
    if outcome.stage:
        lines[0] += "  stopped at {}".format(outcome.stage)
    if obs.det is not None:
        lines.append("det {:.2f}  side {:.0f}px".format(
            obs.det.score, min(obs.det.bbox[2] - obs.det.bbox[0],
                               obs.det.bbox[3] - obs.det.bbox[1])))
    if obs.pose_coarse:
        lines.append("S3 roll {:+.1f}  nose_off {:+.2f}".format(
            obs.pose_coarse["roll"], obs.pose_coarse["nose_offset"]))
    if obs.spoof is not None:
        lines.append("S4 p_real {:.3f} (class {})".format(obs.spoof.p_real, obs.spoof.label))
    if obs.pose_fine:
        lines.append("S5 yaw {:+.1f} pitch {:+.1f} roll {:+.1f}".format(
            obs.pose_fine["yaw"], obs.pose_fine["pitch"], obs.pose_fine["roll"]))
    if obs.iqa:
        lines.append("S5 blur {:.0f}  lum {:.0f}".format(obs.iqa["blur"], obs.iqa["lum"]))
    if obs.quality is not None:
        lines.append("S8 quality {:.3f}".format(obs.quality))
    if outcome.reset:
        lines.append("collector reset: {}".format(outcome.reset))

    for i, text in enumerate(lines):
        cv2.putText(image, text, (12, 28 + 22 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    color if i == 0 else INFO, 2 if i == 0 else 1, cv2.LINE_AA)
    return image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    models = load_models(cfg, strict=False)
    collector = engine_loop.new_collector(cfg)
    source = FileSource(args.video).open()

    writer, index = None, 0
    try:
        while True:
            image = source.read()
            if image is None:
                break
            index += 1
            outcome = engine_loop.process_frame(Frame(index, index / 15.0, image.copy()),
                                                models, cfg, collector)
            annotated = annotate(image, outcome, cfg)
            if writer is None:
                writer = cv2.VideoWriter(args.out, cv2.VideoWriter_fourcc(*"mp4v"), 15.0,
                                         (annotated.shape[1], annotated.shape[0]))
            writer.write(annotated)
            if args.max_frames and index >= args.max_frames:
                break
    finally:
        source.release()
        close_models(models)
        if writer is not None:
            writer.release()
    print("wrote {} frames to {}".format(index, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
