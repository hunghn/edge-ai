# -*- coding: utf-8 -*-
"""Propose thresholds from the DEV split, for a human to approve.

  python tools/eval/calibrate.py --scores results/scores_dev.csv --split data/split.json \
      --far 1e-3 --out docs/results/M9_threshold_proposal.md

Two rules this script enforces rather than trusts:
  * it refuses to run on rows whose participant is in the TEST split;
  * it writes a proposal, never a config. D-01/D-02 stay null in configs/default.yaml
    until a person approves the numbers (the project rule: never invent a threshold).
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from tools.eval import recognition  # noqa: E402
from tools.eval.bootstrap import format_interval  # noqa: E402


def load_scores(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def check_no_test_leak(rows, split_path):
    """A threshold tuned on the test set would make every later number meaningless."""
    if not split_path:
        return None
    with open(split_path) as f:
        split = json.load(f)
    test = set(split.get("test") or [])
    leaked = sorted({row["true_code"] for row in rows} & test)
    if leaked:
        raise SystemExit(
            "these participants are in the TEST split and must not be used for "
            "calibration: {}".format(", ".join(leaked[:10])))
    return split


def margin_sweep(rows, threshold, frr_budget):
    """Per-probe top1 - top2 margins, and what each candidate margin would cost.

    Returns rows of (margin, share of genuine probes kept, share of impostor top-1s cut).
    """
    by_probe = {}
    for row in rows:
        if row.get("score") in ("", None):
            continue
        by_probe.setdefault(row["probe_id"], []).append(row)

    genuine_margins, impostor_margins = [], []
    for candidates in by_probe.values():
        ordered = sorted(candidates, key=lambda r: -float(r["score"]))
        top1 = ordered[0]
        if float(top1["score"]) < threshold:
            continue                     # rejected by the score threshold already
        margin = float(top1["score"]) - (float(ordered[1]["score"]) if len(ordered) > 1
                                         else -1.0)
        (genuine_margins if int(top1["is_genuine"]) == 1
         else impostor_margins).append(margin)

    genuine_margins = np.asarray(genuine_margins)
    impostor_margins = np.asarray(impostor_margins)
    if genuine_margins.size == 0:
        return [], None
    candidates = np.unique(np.round(np.linspace(0.0, float(genuine_margins.max()), 21), 4))
    table = []
    for margin in candidates:
        kept = float(np.mean(genuine_margins >= margin))
        cut = (float(np.mean(impostor_margins < margin)) if impostor_margins.size
               else float("nan"))
        table.append((float(margin), kept, cut))
    # Largest margin whose cost in genuine acceptances stays inside the budget.
    affordable = [row for row in table if (1.0 - row[1]) <= frr_budget]
    best = max(affordable, key=lambda row: row[0]) if affordable else table[0]
    return table, best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True, help="comparison table from the DEV split")
    ap.add_argument("--split", default=None, help="data/split.json, to refuse test leakage")
    ap.add_argument("--far", type=float, default=1e-3, help="D-18 target")
    ap.add_argument("--frr-budget", type=float, default=0.02,
                    help="extra genuine rejections the margin may cost")
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "results",
                                                  "M9_threshold_proposal.md"))
    args = ap.parse_args()

    rows = load_scores(args.scores)
    check_no_test_leak(rows, args.split)
    genuine, impostor = recognition.scores_of(rows)
    if genuine.size == 0 or impostor.size == 0:
        raise SystemExit("need both genuine and impostor comparisons")

    threshold = recognition.threshold_at_far(impostor, args.far)
    summary = recognition.summarise(rows, far_targets=(args.far,), threshold=threshold)
    table, best_margin = margin_sweep(rows, threshold, args.frr_budget)
    no_match = recognition.threshold_at_far(impostor, 1e-2)

    lines = [
        "# M9 — Đề xuất ngưỡng (chờ duyệt)",
        "",
        "> Sinh bởi `tools/eval/calibrate.py` từ **tập dev**. Đây là đề xuất; các giá trị "
        "trong `configs/default.yaml` vẫn để `null` cho tới khi bạn duyệt.",
        "",
        "- nguồn: `{}`".format(args.scores),
        "- số probe: {} | so sánh cùng người: {} | khác người: {}".format(
            summary["n_probes"], summary["n_genuine"], summary["n_impostor"]),
        "- FAR nhỏ nhất đo được: {:.2g} (1 / số phép so sánh khác người)".format(
            summary["smallest_measurable_far"]),
        "",
        "## Đề xuất",
        "",
        "| Khoá config | Giá trị đề xuất | Căn cứ |",
        "|---|---|---|",
        "| `match.threshold` (D-01) | **{:.4f}** | điểm tại FAR = {:g} trên tập dev |".format(
            threshold, args.far),
    ]
    if best_margin:
        lines.append(
            "| `match.margin_top1_top2` (D-02) | **{:.4f}** | giữ {:.1%} probe đúng người, "
            "loại {:.1%} top-1 sai người |".format(best_margin[0], best_margin[1],
                                                   best_margin[2]))
    lines.append("| `decision.no_match_below` (D-04) | **{:.4f}** | điểm tại FAR = 1e-2 "
                 "(vùng chắc chắn không có trong danh sách) |".format(no_match))

    tar = summary["tar_at_far_{:g}".format(args.far)]
    lines += [
        "",
        "## Kèm theo tại ngưỡng đề xuất",
        "",
        "| Chỉ số | Giá trị |",
        "|---|---|",
        "| TAR@FAR={:g} | {} |".format(args.far, format_interval(tar["point"], tar["low"],
                                                                tar["high"])),
        "| FRR (gồm cả phiên low_quality) | {:.4f} |".format(summary["at_threshold"]["frr"]),
        "| FAR thực tế | {:.5f} |".format(summary["at_threshold"]["far"]),
        "| Rank-1 | {} |".format(format_interval(summary["rank1"]["point"],
                                                 summary["rank1"]["low"],
                                                 summary["rank1"]["high"])),
        "| EER | {:.4f} (tại ngưỡng {:.4f}) |".format(summary["eer"],
                                                      summary["eer_threshold"]),
        "",
    ]
    if not tar["measurable"]:
        lines += ["> ⚠️ **FAR = {:g} nằm dưới khả năng đo của tập dữ liệu này** "
                  "({} phép so sánh khác người). Con số TAR ở trên không đáng tin; cần "
                  "thêm người tham gia hoặc báo cáo ở mức FAR cao hơn.".format(
                      args.far, summary["n_impostor"]), ""]
    if table:
        lines += ["## Quét margin", "", "| margin | giữ lại (đúng người) | loại bỏ (sai người) |",
                  "|---|---|---|"]
        for margin, kept, cut in table[::2]:
            lines.append("| {:.4f} | {:.1%} | {:.1%} |".format(margin, kept, cut))
        lines.append("")
    lines += ["## Việc cần làm",
              "",
              "1. Xem lại các con số ở trên.",
              "2. Nếu đồng ý: ghi vào `configs/default.yaml` và chuyển D-01/D-02/D-04 sang "
              "phần *Đã chốt* của `docs/plans/decisions.md`.",
              "3. Chỉ sau đó mới chạy đánh giá trên **tập test**."]

    directory = os.path.dirname(args.out)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:16]))
    print("\nwrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
