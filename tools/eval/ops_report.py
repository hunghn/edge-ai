# -*- coding: utf-8 -*-
"""Operational metrics of spec §5, from the sessions table.

  python tools/eval/ops_report.py --db var/edge.db --out docs/results/ops.md

These are the numbers a clinic feels: how often the nurse has to look twice, how often a
patient is asked to try again, and how many attempts a successful identification takes.
"""
import argparse
import collections
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface.storage import clock, db  # noqa: E402
from edgeface.storage.db import read_all  # noqa: E402


def attempts_per_success(sessions):
    """Mean number of sessions between successful confirmations.

    A `retry` closes one session and opens another, so counting sessions per confirmed
    identification is exactly "how many times did the patient have to stand there".
    """
    ordered = sorted(sessions, key=lambda row: row["started_at"])
    runs, current = [], 0
    for row in ordered:
        if row["kind"] != "identify":
            continue
        current += 1
        if row["nurse_action"] in ("confirm", "manual"):
            runs.append(current)
            current = 0
    return (sum(runs) / float(len(runs))) if runs else float("nan")


def summarise(conn, since):
    sessions = read_all(conn, "SELECT * FROM sessions WHERE started_at >= ?", (since,))
    identify = [row for row in sessions if row["kind"] == "identify"]
    total = len(identify)
    decisions = collections.Counter(row["decision"] or "none" for row in identify)
    actions = collections.Counter(row["nurse_action"] or "none" for row in identify)
    rules = collections.Counter(row["rule_id"] or "none" for row in identify)
    return {
        "total_identify": total,
        "total_enroll": len(sessions) - total,
        "by_decision": dict(decisions),
        "by_nurse_action": dict(actions),
        "by_rule": dict(rules),
        "review_required_rate": decisions.get("review_required", 0) / total if total else 0.0,
        "low_quality_rate": decisions.get("low_quality", 0) / total if total else 0.0,
        "spoof_rate": decisions.get("spoof_suspect", 0) / total if total else 0.0,
        "manual_rate": actions.get("manual", 0) / total if total else 0.0,
        "attempts_per_success": attempts_per_success(sessions),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = db.open_db(args.db)
    try:
        summary = summarise(conn, clock.now() - args.days * 86400.0)
    finally:
        conn.close()

    lines = ["# Chỉ số vận hành (spec §5)", "",
             "- nguồn: `{}` · {} ngày gần nhất".format(args.db, args.days),
             "- số phiên nhận dạng: {} · số phiên đăng ký: {}".format(
                 summary["total_identify"], summary["total_enroll"]), "",
             "| Chỉ số | Giá trị |", "|---|---|",
             "| Tỉ lệ `review_required` | {:.1%} |".format(summary["review_required_rate"]),
             "| Tỉ lệ `low_quality` | {:.1%} |".format(summary["low_quality_rate"]),
             "| Tỉ lệ nghi giả mạo | {:.1%} |".format(summary["spoof_rate"]),
             "| Tỉ lệ điều dưỡng phải tìm thủ công | {:.1%} |".format(summary["manual_rate"]),
             "| Số lượt thử trung bình để định danh xong | {:.2f} |".format(
                 summary["attempts_per_success"]), "",
             "## Theo luật quyết định", "", "| Luật | Số phiên |", "|---|---|"]
    for rule, count in sorted(summary["by_rule"].items()):
        lines.append("| {} | {} |".format(rule, count))
    lines += ["", "## Theo hành động của điều dưỡng", "", "| Hành động | Số phiên |",
              "|---|---|"]
    for action, count in sorted(summary["by_nurse_action"].items()):
        lines.append("| {} | {} |".format(action, count))

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
