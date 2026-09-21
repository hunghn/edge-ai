"""Run S0-S8 over a recorded video and report what happened, frame by frame.

This is the repeatable benchmark for the pipeline: same video, same numbers, on a dev
machine (onnxruntime) or on the Nano (TensorRT).

  python3 scripts/run_pipeline_offline.py --video data/videos/sample.mp4 \
      --config configs/dev.yaml --out results/run1

Outputs in --out:
  frames.csv    one row per frame: stopping stage, reason, per-stage latency
  embeddings.npz  the embeddings the collector kept, with their quality
  summary.md    latency table (p50/p95), FPS, and where frames were rejected
"""
import argparse
import csv
import collections
import os
import sys
import time

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.common.timing import RECORDER  # noqa: E402
from edgeface.engine import loop as engine_loop  # noqa: E402
from edgeface.engine.models import close_models, load_models  # noqa: E402
from edgeface.pipeline import best_frame as bf  # noqa: E402
from edgeface.pipeline.capture import FileSource  # noqa: E402
from edgeface.types import Frame  # noqa: E402

STAGE_ORDER = ["S1", "S2", "S3", "S4", "S5_landmark", "S5", "S6", "S7", "e2e"]


def frame_row(index, outcome, elapsed_ms):
    obs = outcome.obs
    row = {
        "frame_id": index,
        "stopped_at": outcome.stage or "",
        "reason": outcome.guidance or "",
        "collector": outcome.collector,
        "reset": outcome.reset or "",
        "e2e_ms": round(elapsed_ms, 2),
        "det_score": round(obs.det.score, 4) if obs.det is not None else "",
        "bbox_side": round(min(obs.det.bbox[2] - obs.det.bbox[0],
                               obs.det.bbox[3] - obs.det.bbox[1]), 1) if obs.det else "",
    }
    if obs.pose_coarse:
        row["coarse_roll"] = round(obs.pose_coarse["roll"], 2)
        row["nose_offset"] = round(obs.pose_coarse["nose_offset"], 4)
    if obs.spoof is not None:
        row["p_real"] = round(obs.spoof.p_real, 4)
    if obs.pose_fine:
        row["yaw"] = round(obs.pose_fine["yaw"], 2)
        row["pitch"] = round(obs.pose_fine["pitch"], 2)
        row["roll"] = round(obs.pose_fine["roll"], 2)
    if obs.iqa:
        row["blur"] = round(obs.iqa["blur"], 1)
        row["lum"] = round(obs.iqa["lum"], 1)
    if obs.quality is not None:
        row["quality"] = round(obs.quality, 4)
    return row


def write_summary(path, rows, collected, wall_s, cfg, args):
    stages = RECORDER.summary()
    stopped = collections.Counter(row["stopped_at"] or "passed" for row in rows)
    reasons = collections.Counter(row["reason"] for row in rows if row["reason"])
    lines = [
        "# Offline pipeline run",
        "",
        "- video: `{}`".format(args.video),
        "- config: `{}` (backend {})".format(args.config, cfg_mod.get(cfg, "backend")),
        "- frames: {} in {:.1f} s -> {:.1f} FPS processed".format(
            len(rows), wall_s, len(rows) / wall_s if wall_s else 0.0),
        "- embeddings kept: {}".format(len(collected)),
        "",
        "## Latency per stage (ms)",
        "> The first frame includes model warm-up, which dominates the `max` column.",
        "",
        "| stage | n | mean | p50 | p95 | max |",
        "|---|---|---|---|---|---|",
    ]
    for stage in STAGE_ORDER:
        s = stages.get(stage)
        if s:
            lines.append("| {} | {} | {:.2f} | {:.2f} | {:.2f} | {:.2f} |".format(
                stage, s["n"], s["mean"], s["p50"], s["p95"], s["max"]))
    lines += ["", "## Where frames stopped", "", "| stage | frames | share |", "|---|---|---|"]
    for stage, count in stopped.most_common():
        lines.append("| {} | {} | {:.1f}% |".format(stage, count, 100.0 * count / len(rows)))
    lines += ["", "## Guidance shown", "", "| reason | frames |", "|---|---|"]
    for reason, count in reasons.most_common():
        lines.append("| {} | {} |".format(reason, count))
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", default=os.path.join(REPO, "results", "offline"))
    ap.add_argument("--realtime", action="store_true",
                    help="pace playback like a live camera instead of processing every frame")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--keep-collecting", action="store_true",
                    help="do not reset the collector after a READY batch (debugging)")
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    os.makedirs(args.out, exist_ok=True)
    RECORDER.reset()

    models = load_models(cfg, strict=False)
    collector = engine_loop.new_collector(cfg)
    source = FileSource(args.video, realtime=args.realtime).open()

    rows, collected, batches = [], [], 0
    index = 0
    started = time.time()
    try:
        while True:
            image = source.read()
            if image is None:
                break
            index += 1
            frame = Frame(index, time.time(), image)
            t0 = time.time()
            outcome = engine_loop.process_frame(frame, models, cfg, collector)
            rows.append(frame_row(index, outcome, (time.time() - t0) * 1000.0))

            if outcome.collector == bf.READY and not args.keep_collecting:
                status, embeddings, n_good = collector.result(frame.ts)
                batches += 1
                for emb in embeddings:
                    collected.append((index, emb.quality, emb.vector))
                print("  batch {}: {} embeddings ({} good frames)".format(
                    batches, len(embeddings), n_good))
                collector.reset(bf.RESET_CONSUMED)
            elif outcome.collector == bf.LOW_QUALITY:
                print("  low_quality after {} good frames".format(collector.n_good))
                collector.reset(bf.RESET_CONSUMED)

            if args.max_frames and index >= args.max_frames:
                break
    finally:
        source.release()
        close_models(models)
    wall_s = time.time() - started

    if not rows:
        raise SystemExit("no frames read from " + args.video)

    fieldnames = sorted({key for row in rows for key in row})
    with open(os.path.join(args.out, "frames.csv"), "w") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    np.savez_compressed(
        os.path.join(args.out, "embeddings.npz"),
        frame_id=np.asarray([c[0] for c in collected], dtype=np.int32),
        quality=np.asarray([-1.0 if c[1] is None else c[1] for c in collected],
                           dtype=np.float32),
        vectors=(np.vstack([c[2] for c in collected]) if collected
                 else np.zeros((0, 512), dtype=np.float32)))
    write_summary(os.path.join(args.out, "summary.md"), rows, collected, wall_s, cfg, args)

    print("\n{} frames in {:.1f}s -> {:.1f} FPS | {} batches, {} embeddings".format(
        len(rows), wall_s, len(rows) / wall_s, batches, len(collected)))
    print("wrote", os.path.join(args.out, "summary.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
