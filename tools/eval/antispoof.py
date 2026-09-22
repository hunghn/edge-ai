# -*- coding: utf-8 -*-
"""Presentation-attack metrics, in the spirit of ISO/IEC 30107-3.

APCER is reported per attack species and then as the WORST of them, not the average:
an attack that works is a way in, and averaging it with three that fail hides exactly the
thing the clinic needs to know.
"""
import numpy as np

from tools.eval.bootstrap import by_participant


def _scores(rows, attack):
    values = [float(r["p_real"]) for r in rows
              if r.get("p_real") not in ("", None) and int(r.get("is_attack", 0)) == attack]
    return np.asarray(values, dtype=np.float64)


def apcer_by_species(rows, threshold):
    """{pai_type: share of that attack accepted as real}."""
    species = {}
    for row in rows:
        if int(row.get("is_attack", 0)) != 1 or row.get("p_real") in ("", None):
            continue
        species.setdefault(row.get("pai_type") or "unknown", []).append(float(row["p_real"]))
    return {name: float(np.mean(np.asarray(values) >= threshold))
            for name, values in sorted(species.items())}


def apcer(rows, threshold):
    """The worst species, as ISO/IEC 30107-3 defines the overall APCER."""
    by_species = apcer_by_species(rows, threshold)
    return max(by_species.values()) if by_species else float("nan")


def apcer_mean(rows, threshold):
    by_species = apcer_by_species(rows, threshold)
    return float(np.mean(list(by_species.values()))) if by_species else float("nan")


def bpcer(rows, threshold):
    """Share of genuine presentations wrongly rejected as attacks."""
    real = _scores(rows, attack=0)
    return float(np.mean(real < threshold)) if real.size else float("nan")


def acer(rows, threshold):
    """(APCER + BPCER) / 2.

    The current edition of ISO/IEC 30107-3 no longer recommends ACER, because averaging
    two rates with different operational meanings hides the trade-off. The spec asks for
    it, so it is reported — next to the two numbers it averages.
    """
    return (apcer(rows, threshold) + bpcer(rows, threshold)) / 2.0


def det_points(rows, steps=256):
    """(threshold, apcer, bpcer) across the p_real range, for the PAD DET curve."""
    all_scores = np.concatenate([_scores(rows, 0), _scores(rows, 1)])
    if all_scores.size == 0:
        return []
    lo, hi = float(all_scores.min()), float(all_scores.max())
    return [(float(t), apcer(rows, t), bpcer(rows, t))
            for t in np.linspace(lo, hi, steps)]


def bpcer_at_apcer(rows, apcer_target):
    """BPCER at the operating point where APCER first drops to the target."""
    points = [p for p in det_points(rows) if np.isfinite(p[1]) and p[1] <= apcer_target]
    if not points:
        return float("nan"), float("nan")
    best = min(points, key=lambda p: p[2])
    return best[2], best[0]


def summarise(rows, threshold, rounds=200):
    real, attacks = _scores(rows, 0), _scores(rows, 1)
    result = {
        "threshold": threshold,
        "n_real": int(real.size),
        "n_attack": int(attacks.size),
        "apcer_by_species": apcer_by_species(rows, threshold),
        "apcer_mean": apcer_mean(rows, threshold),
    }
    point, low, high = by_participant(rows, lambda r: apcer(r, threshold), rounds=rounds)
    result["apcer"] = {"point": point, "low": low, "high": high}
    point, low, high = by_participant(rows, lambda r: bpcer(r, threshold), rounds=rounds)
    result["bpcer"] = {"point": point, "low": low, "high": high}
    result["acer"] = acer(rows, threshold)
    for target in (0.05, 0.10):
        value, at_threshold = bpcer_at_apcer(rows, target)
        result["bpcer_at_apcer_{:g}".format(target)] = {"bpcer": value,
                                                        "threshold": at_threshold}
    return result
