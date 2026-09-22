# -*- coding: utf-8 -*-
"""Performance table from the device's own metrics database.

  python tools/eval/perf_report.py --db var/edge.db --out docs/results/perf.md

The engine writes one stage_latency row per session (the median of that session), so the
numbers here are what the kiosk actually did, not a synthetic benchmark.
"""
import argparse
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface.storage import clock, db, metrics  # noqa: E402

STAGE_ORDER = ["S1", "S2", "S3", "S4", "S5_landmark", "S5", "S6", "S7", "S9", "S10", "e2e"]
STAGE_NAMES = {
    "S1": "phát hiện mặt", "S2": "chọn chủ thể", "S3": "tư thế thô",
    "S4": "chống giả mạo", "S5_landmark": "landmark", "S5": "tư thế tinh + IQA",
    "S6": "căn chỉnh", "S7": "trích đặc trưng", "S9": "so khớp", "S10": "quyết định",
    "e2e": "toàn frame",
}


def percentiles(values):
    array = np.asarray(values, dtype=np.float64)
    return {"n": int(array.size), "mean": float(array.mean()),
            "p50": float(np.percentile(array, 50)), "p95": float(np.percentile(array, 95)),
            "max": float(array.max())}


def stage_table(conn, since=None):
    rows = metrics.samples(conn, since)
    by_stage = {}
    for row in rows:
        by_stage.setdefault(row["stage"], []).append(row["ms"])
    return {stage: percentiles(values) for stage, values in by_stage.items() if values}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = db.open_db(args.db)
    try:
        since = clock.now() - args.days * 86400.0
        table = stage_table(conn, since)
    finally:
        conn.close()
    if not table:
        raise SystemExit("no stage_latency rows in the last {} day(s)".format(args.days))

    lines = ["# Hiệu năng theo stage (từ `stage_latency` của thiết bị)", "",
             "- nguồn: `{}` · {} ngày gần nhất".format(args.db, args.days), "",
             "| Stage | | n | mean | p50 | p95 | max |", "|---|---|---|---|---|---|---|"]
    for stage in STAGE_ORDER + sorted(set(table) - set(STAGE_ORDER)):
        stats = table.get(stage)
        if not stats:
            continue
        lines.append("| {} | {} | {} | {:.2f} | {:.2f} | {:.2f} | {:.2f} |".format(
            stage, STAGE_NAMES.get(stage, ""), stats["n"], stats["mean"], stats["p50"],
            stats["p95"], stats["max"]))
    e2e = table.get("e2e")
    if e2e:
        lines += ["", "FPS tương đương theo p50: **{:.1f}**".format(1000.0 / e2e["p50"])]
    text = "\n".join(lines) + "\n"
    if args.out:
        directory = os.path.dirname(args.out)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w") as f:
            f.write(text)
        print("wrote", args.out)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
