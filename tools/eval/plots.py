# -*- coding: utf-8 -*-
"""ROC, DET and PAD curves for the report.

  python tools/eval/plots.py --scores results/scores_test.csv --out docs/figures/eval

DET axes use the normal deviate scale, as the biometrics literature does: on that scale a
pair of Gaussian score distributions plots as a straight line, which makes two systems
easy to compare by eye.
"""
import argparse
import csv
import math
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO)

from tools.eval import antispoof, recognition  # noqa: E402

# Matched to docs/plans: one colour per system, consistent across every figure.
COLOURS = {"edgeface": "#1f6f43", "lbph": "#a3242c", "other": "#3b5bdb"}


def norm_ppf(p):
    """Inverse normal CDF (Acklam's approximation); avoids a scipy dependency."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def by_system(rows):
    systems = {}
    for row in rows:
        systems.setdefault(row.get("system") or "edgeface", []).append(row)
    return systems


def plot_roc(systems, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(6, 5))
    for name, rows in sorted(systems.items()):
        points = recognition.roc_points(rows)
        if not points:
            continue
        axes.plot([p[0] for p in points], [p[1] for p in points],
                  label=name, color=COLOURS.get(name, COLOURS["other"]), linewidth=2)
    axes.set_xscale("log")
    axes.set_xlabel("FAR (tỉ lệ nhận nhầm người khác)")
    axes.set_ylabel("TAR (tỉ lệ nhận đúng)")
    axes.set_title("Đường cong ROC")
    axes.grid(True, which="both", alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def plot_det(systems, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Sparse enough that the labels do not collide once mapped onto the deviate scale.
    ticks = [0.001, 0.01, 0.05, 0.2, 0.4]
    figure, axes = plt.subplots(figsize=(6, 5))
    for name, rows in sorted(systems.items()):
        points = recognition.roc_points(rows)
        if not points:
            continue
        far = [max(p[0], 1e-6) for p in points]
        frr = [max(1.0 - p[1], 1e-6) for p in points]
        axes.plot([norm_ppf(x) for x in far], [norm_ppf(y) for y in frr],
                  label=name, color=COLOURS.get(name, COLOURS["other"]), linewidth=2)
    axes.set_xticks([norm_ppf(t) for t in ticks])
    axes.set_xticklabels(["{:g}%".format(t * 100) for t in ticks], rotation=0)
    axes.set_xlim(norm_ppf(0.0008), norm_ppf(0.5))
    axes.set_ylim(norm_ppf(0.0008), norm_ppf(0.5))
    axes.set_yticks([norm_ppf(t) for t in ticks])
    axes.set_yticklabels(["{:g}%".format(t * 100) for t in ticks])
    axes.set_xlabel("FAR")
    axes.set_ylabel("FRR")
    axes.set_title("Đường cong DET (thang normal deviate)")
    axes.grid(True, alpha=0.3)
    axes.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def plot_pad(rows, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = antispoof.det_points(rows)
    if not points:
        return None
    figure, axes = plt.subplots(figsize=(6, 5))
    axes.plot([p[1] for p in points], [p[2] for p in points], color=COLOURS["edgeface"],
              linewidth=2)
    axes.set_xlabel("APCER (tấn công bị nhận là thật)")
    axes.set_ylabel("BPCER (người thật bị từ chối)")
    axes.set_title("Đường cong PAD")
    axes.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--pad-scores", default=None, help="table with p_real / is_attack")
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "figures", "eval"))
    args = ap.parse_args()

    if not os.path.isdir(args.out):
        os.makedirs(args.out)
    systems = by_system(load(args.scores))
    print("wrote", plot_roc(systems, os.path.join(args.out, "roc.png")))
    print("wrote", plot_det(systems, os.path.join(args.out, "det.png")))
    if args.pad_scores:
        written = plot_pad(load(args.pad_scores), os.path.join(args.out, "pad.png"))
        if written:
            print("wrote", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
