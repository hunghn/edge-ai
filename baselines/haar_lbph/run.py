# -*- coding: utf-8 -*-
"""Run the LBPH baseline over a video and emit the same artefacts as the main pipeline.

  python3 baselines/haar_lbph/run.py --video probe.mp4 --out results/baseline_run

So that M9 can compare like with like:
  * per-stage latency through the same edgeface.common.timing recorder;
  * scores.csv in the same shape as tools/dataset/extract_scores.py writes.

LBPH returns a distance (lower is closer) while the main pipeline returns a cosine
similarity (higher is closer). The score column is negated here so one ROC/DET
implementation serves both.
"""
import argparse
import csv
import json
import os
import sys
import time

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, REPO)

from baselines.haar_lbph.detector import detector_from_config, face_chip  # noqa: E402
from baselines.haar_lbph.lbph import LBPHRecognizer  # noqa: E402
from edgeface import config as cfg_mod  # noqa: E402
from edgeface.common.timing import RECORDER  # noqa: E402
from edgeface.pipeline.capture import FileSource  # noqa: E402

STAGE_ORDER = ["B1", "B2", "B3", "b2e"]


def load_model(cfg, model_path=None):
    baseline = cfg["baseline"]
    path = model_path or os.path.join(REPO, baseline["model_path"])
    model = LBPHRecognizer.load(path)
    model.threshold = baseline.get("threshold")
    labels = {}
    if os.path.exists(path + ".labels.json"):
        with open(path + ".labels.json") as f:
            labels = json.load(f)
    return model, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "baseline.yaml"))
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--label", default=None,
                    help="true identity of this clip, for the genuine/impostor column")
    ap.add_argument("--out", default=os.path.join(REPO, "results", "baseline"))
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    detector = detector_from_config(cfg)
    model, names = load_model(cfg, args.model)
    chip_size = cfg["baseline"]["chip_size"]
    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    RECORDER.reset()

    source = FileSource(args.video).open()
    rows, index, started = [], 0, time.time()
    try:
        while True:
            image = source.read()
            if image is None:
                break
            index += 1
            frame_started = time.time()
            box = detector.largest(image)
            row = {"frame_id": index, "detected": int(box is not None)}
            if box is not None:
                chip = face_chip(image, box, chip_size)
                if chip is not None:
                    t0 = time.time()
                    label, distance = model.predict(chip)
                    RECORDER.add("B3", (time.time() - t0) * 1000.0)
                    row.update({
                        "predicted_label": label,
                        "predicted_code": names.get(str(label), ""),
                        "distance": round(distance, 4),
                        # Negated so "higher is better", like the cosine score.
                        "score": round(-distance, 4),
                        "bbox_side": round(min(box[2] - box[0], box[3] - box[1]), 1),
                    })
            RECORDER.add("b2e", (time.time() - frame_started) * 1000.0)
            rows.append(row)
            if args.max_frames and index >= args.max_frames:
                break
    finally:
        source.release()
    wall = time.time() - started

    if not rows:
        raise SystemExit("no frames read from " + args.video)
    fieldnames = sorted({key for row in rows for key in row})
    with open(os.path.join(args.out, "frames.csv"), "w") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    if args.label:
        with open(os.path.join(args.out, "scores.csv"), "w") as f:
            writer = csv.writer(f)
            writer.writerow(["probe_id", "true_code", "claimed_code", "score", "is_genuine",
                             "system"])
            for row in rows:
                if "predicted_code" not in row:
                    continue
                writer.writerow(["{}#{}".format(os.path.basename(args.video), row["frame_id"]),
                                 args.label, row["predicted_code"], row["score"],
                                 int(row["predicted_code"] == args.label), "lbph"])

    summary = RECORDER.summary()
    detected = sum(row["detected"] for row in rows)
    lines = ["# Haar + LBPH baseline run", "",
             "- video: `{}`".format(args.video),
             "- frames: {} in {:.1f} s -> {:.1f} FPS".format(len(rows), wall,
                                                             len(rows) / wall if wall else 0),
             "- frames with a detected face: {} ({:.0f}%)".format(
                 detected, 100.0 * detected / len(rows)),
             "", "| stage | n | mean | p50 | p95 |", "|---|---|---|---|---|"]
    for stage in STAGE_ORDER:
        s = summary.get(stage)
        if s:
            lines.append("| {} | {} | {:.2f} | {:.2f} | {:.2f} |".format(
                stage, s["n"], s["mean"], s["p50"], s["p95"]))
    lines += ["", "B1 = Haar detect, B2 = crop/equalise, B3 = LBPH match, b2e = whole frame."]
    with open(os.path.join(args.out, "summary.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[3:6]))
    print("wrote", os.path.join(args.out, "summary.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
