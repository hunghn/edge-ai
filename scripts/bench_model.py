"""Per-model latency benchmark (M2-T10). Runs on the Nano (TensorRT) or on a dev machine
(onnxruntime), using the same wrappers as the pipeline.

For every model it times pre-process, inference and post-process separately, so the
numbers can be compared with the per-stage budget of the pipeline later.

Usage:
  python3 scripts/bench_model.py --all [--config configs/nano.yaml]
                                 [--warmup 50] [--iters 500] [--csv out.csv]
  python3 scripts/bench_model.py --model detector --iters 200
"""
import argparse
import csv
import os
import sys
import time

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.models.arcface import ArcFace  # noqa: E402
from edgeface.models.landmark106 import Landmark106  # noqa: E402
from edgeface.models.minifasnet import MiniFASNet  # noqa: E402
from edgeface.common.imgproc import l2_normalize, softmax  # noqa: E402
from edgeface.models.scrfd import SCRFD  # noqa: E402
from edgeface.pipeline.align import norm_crop  # noqa: E402
from edgeface.runtime import create_backend  # noqa: E402

MODEL_KEYS = ["detector", "landmark", "recognizer", "antispoof_v2", "antispoof_v1se"]
FIXTURE = os.path.join(REPO, "tests", "fixtures", "astronaut.jpg")


def rss_peak_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024.0
    except IOError:
        pass
    return float("nan")


def stats(samples_ms):
    a = np.asarray(samples_ms, dtype=np.float64)
    return {
        "n": int(a.size),
        "mean": float(a.mean()),
        "p50": float(np.percentile(a, 50)),
        "p95": float(np.percentile(a, 95)),
        "max": float(a.max()),
    }


def time_calls(fn, warmup, iters):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(iters):
        t0 = time.time()
        fn()
        samples.append((time.time() - t0) * 1000.0)
    return samples


def build_case(key, cfg, image):
    """Return (name, pre_fn, infer_fn, post_fn) for one logical model."""
    backend_kind = cfg_mod.get(cfg, "backend")
    model_dir = os.path.join(REPO, cfg_mod.get(cfg, "models.dir"))
    stem = cfg_mod.get(cfg, "models." + key)
    backend = create_backend(backend_kind, model_dir, stem)
    input_name = backend.inputs[0].name

    h, w = image.shape[:2]
    side = min(h, w) * 0.4
    bbox = [w / 2.0 - side / 2, h / 2.0 - side / 2, w / 2.0 + side / 2, h / 2.0 + side / 2]

    if key == "detector":
        model = SCRFD(backend, input_size=tuple(cfg_mod.get(cfg, "detect.input_size")),
                      nms_iou=cfg_mod.get(cfg, "detect.nms_iou"))
        score_min = cfg_mod.get(cfg, "detect.score_min")
        blob, scale = model.preprocess(image)
        outputs = list(backend.infer({input_name: blob}).values())
        return (stem,
                lambda: model.preprocess(image),
                lambda: backend.infer({input_name: blob}),
                lambda: model.postprocess(outputs, scale, score_min))

    if key == "landmark":
        model = Landmark106(backend, mean=0.0, std=1.0,
                            input_size=cfg_mod.get(cfg, "landmark.input_size"),
                            bbox_expand=cfg_mod.get(cfg, "landmark.bbox_expand"))
        blob, m = model.preprocess(image, bbox)
        out = list(backend.infer({input_name: blob}).values())[0]
        return (stem,
                lambda: model.preprocess(image, bbox),
                lambda: backend.infer({input_name: blob}),
                lambda: model.postprocess(out, m))

    if key == "recognizer":
        model = ArcFace(backend)
        kps = np.array([[38.3, 51.7], [73.5, 51.5], [56.0, 71.7], [41.5, 92.4], [70.7, 92.2]],
                       dtype=np.float32) * (side / 112.0) + np.array([bbox[0], bbox[1]])
        aligned = norm_crop(image, kps)
        blob = model.preprocess(aligned)
        out = list(backend.infer({input_name: blob}).values())[0]
        return (stem,
                lambda: model.preprocess(aligned),
                lambda: backend.infer({input_name: blob}),
                lambda: l2_normalize(np.asarray(out, dtype=np.float32).reshape(-1)))

    scale_key = "antispoof.crops"
    crops = cfg_mod.get(cfg, scale_key)
    scale = next(c["scale"] for c in crops if c["model"] == key)
    model = MiniFASNet(backend, scale=scale,
                       input_size=tuple(cfg_mod.get(cfg, "antispoof.input_size")))
    bbox_xywh = [bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1]]
    blob = model.preprocess(image, bbox_xywh)
    logits = list(backend.infer({input_name: blob}).values())[0]
    return (stem,
            lambda: model.preprocess(image, bbox_xywh),
            lambda: backend.infer({input_name: blob}),
            lambda: softmax(np.asarray(logits, dtype=np.float32).reshape(1, -1))[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    ap.add_argument("--model", action="append", choices=MODEL_KEYS,
                    help="repeatable; default is --all")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--warmup", type=int, default=50)
    ap.add_argument("--iters", type=int, default=500)
    ap.add_argument("--image", default=FIXTURE)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--tegrastats", action="store_true", help="also record RAM/power")
    ap.add_argument("--tegrastats-sudo", action="store_true",
                    help="run tegrastats via sudo -n; needed for the POM_* power rails")
    args = ap.parse_args()

    keys = MODEL_KEYS if (args.all or not args.model) else args.model
    cfg = cfg_mod.load_config(args.config)
    image = cv2.imread(args.image)
    if image is None:
        raise SystemExit("cannot read image " + args.image)

    monitor = None
    if args.tegrastats:
        from edgeface.metrics.tegrastats import TegrastatsMonitor
        monitor = TegrastatsMonitor(sudo=args.tegrastats_sudo).start()

    rows = []
    for key in keys:
        name, pre, infer, post = build_case(key, cfg, image)
        pre_s = stats(time_calls(pre, args.warmup, args.iters))
        inf_s = stats(time_calls(infer, args.warmup, args.iters))
        post_s = stats(time_calls(post, args.warmup, args.iters))
        total_p50 = pre_s["p50"] + inf_s["p50"] + post_s["p50"]
        rows.append({
            "model": name, "key": key,
            "pre_p50": pre_s["p50"], "infer_p50": inf_s["p50"], "post_p50": post_s["p50"],
            "infer_mean": inf_s["mean"], "infer_p95": inf_s["p95"], "infer_max": inf_s["max"],
            "total_p50": total_p50, "fps_equiv": 1000.0 / total_p50,
            "iters": args.iters,
        })
        print("  done: {:22s} total p50 {:7.2f} ms".format(name, total_p50))

    print("\n| model | pre p50 | infer p50 | infer p95 | post p50 | total p50 | ~FPS |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print("| {model} | {pre_p50:.2f} | {infer_p50:.2f} | {infer_p95:.2f} | {post_p50:.2f} "
              "| {total_p50:.2f} | {fps_equiv:.1f} |".format(**r))
    worst_case = sum(r["total_p50"] for r in rows)
    print("\nSum of all models (worst case, every model once per frame): "
          "{:.1f} ms -> {:.1f} FPS".format(worst_case, 1000.0 / worst_case))
    print("Process peak RSS: {:.0f} MB".format(rss_peak_mb()))

    if monitor is not None:
        summary = monitor.stop().summary()
        if summary:
            print("tegrastats: RAM peak {} MB, GPU mean {:.0f}%, CPU total {:.0f}%".format(
                summary.get("ram_peak_mb"), summary.get("gpu_pct_mean", float("nan")),
                summary.get("cpu_pct_mean_total", float("nan"))))
            for rail, vals in sorted(summary.get("power_mw", {}).items()):
                print("  {:12s} mean {:.0f} mW, peak {:.0f} mW".format(
                    rail, vals["mean"], vals["peak"]))
            if summary.get("temp_c_peak"):
                print("  temps peak:", {k: v for k, v in sorted(
                    summary["temp_c_peak"].items()) if k in ("CPU", "GPU", "thermal")})

    if args.csv:
        with open(args.csv, "w") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(rows[0]))
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        print("wrote", args.csv)


if __name__ == "__main__":
    main()
