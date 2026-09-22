# -*- coding: utf-8 -*-
"""Run an ablation: same clips, same gallery, one setting changed at a time.

  python tools/eval/run_matrix.py --experiment experiments/A1_fusion.yaml

Each variant re-runs extract_scores with a config override and reports the recognition
metrics side by side, so a claim like "the two anti-spoof models are worth keeping" comes
with the number that supports it.

Every variant writes its own scores file, so a result can be re-checked later without
re-running the pipeline.
"""
import argparse
import copy
import csv
import json
import os
import subprocess
import sys

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from tools.eval import recognition  # noqa: E402
from tools.eval.bootstrap import format_interval  # noqa: E402


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def write_variant_config(base_config_path, override, path):
    with open(base_config_path) as f:
        base = yaml.safe_load(f) or {}
    merged = deep_merge(base, override)
    with open(path, "w") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, default_flow_style=False)
    return path


def run_variant(experiment, variant, workdir):
    name = variant["name"]
    variant_dir = os.path.join(workdir, name)
    if not os.path.isdir(variant_dir):
        os.makedirs(variant_dir)
    config_path = write_variant_config(
        os.path.join(REPO, experiment["config"]), variant.get("config_override"),
        os.path.join(variant_dir, "config.yaml"))
    scores_path = os.path.join(variant_dir, "scores.csv")

    command = [sys.executable, os.path.join(REPO, "tools", "dataset", "extract_scores.py"),
               "--config", config_path, "--gallery-db", os.path.join(REPO,
                                                                     experiment["gallery_db"]),
               "--out", scores_path, "--probes"] + experiment["probes"]
    print("  running", name)
    result = subprocess.run(command, cwd=REPO, capture_output=True)
    if result.returncode != 0:
        print(result.stdout.decode()[-2000:], result.stderr.decode()[-2000:])
        raise SystemExit("variant {} failed".format(name))
    with open(scores_path) as f:
        rows = list(csv.DictReader(f))
    return scores_path, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--experiment", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--far", type=float, default=1e-3)
    ap.add_argument("--rounds", type=int, default=200)
    args = ap.parse_args()

    with open(args.experiment) as f:
        experiment = yaml.safe_load(f)
    workdir = os.path.join(REPO, experiment.get("out", os.path.join(
        "results", os.path.splitext(os.path.basename(args.experiment))[0])))
    if not os.path.isdir(workdir):
        os.makedirs(workdir)

    print("experiment:", experiment.get("name", args.experiment))
    results = []
    for variant in experiment["variants"]:
        scores_path, rows = run_variant(experiment, variant, workdir)
        summary = recognition.summarise(rows, far_targets=(args.far,), rounds=args.rounds)
        results.append({"name": variant["name"], "note": variant.get("note", ""),
                        "scores": scores_path, "summary": summary})

    key = "tar_at_far_{:g}".format(args.far)
    lines = ["# {}".format(experiment.get("name", "Ablation")), "",
             experiment.get("question", ""), "",
             "| Biến thể | TAR@FAR={:g} | Rank-1 | EER | Ghi chú |".format(args.far),
             "|---|---|---|---|---|"]
    for item in results:
        summary = item["summary"]
        tar = summary[key]
        lines.append("| {} | {} | {} | {:.4f} | {} |".format(
            item["name"], format_interval(tar["point"], tar["low"], tar["high"]),
            format_interval(summary["rank1"]["point"], summary["rank1"]["low"],
                            summary["rank1"]["high"]),
            summary["eer"], item["note"]))
    if results and not results[0]["summary"][key]["measurable"]:
        lines += ["", "> ⚠️ FAR = {:g} nằm dưới khả năng đo của tập này; so sánh bằng EER "
                  "và Rank-1 thay vì TAR.".format(args.far)]
    lines += ["", "Bảng điểm từng biến thể nằm trong `{}`.".format(
        os.path.relpath(workdir, REPO))]

    out = args.out or os.path.join(workdir, "report.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    with open(os.path.join(workdir, "results.json"), "w") as f:
        json.dump([{k: v for k, v in item.items() if k != "scores"} for item in results],
                  f, indent=2, default=str)
    print("\n".join(lines))
    print("\nwrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
