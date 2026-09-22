# -*- coding: utf-8 -*-
"""Recognition metrics: TAR@FAR, FRR, Rank-1, ROC and DET.

Input is the comparison table from tools/dataset/extract_scores.py: one row per
(probe, gallery identity) with a score and is_genuine. Every metric is computed from
those two columns, so the same code serves the main pipeline and the LBPH baseline
(whose distance is already negated into a similarity).
"""
import numpy as np

from tools.eval.bootstrap import by_participant


def scores_of(rows):
    genuine = np.array([float(r["score"]) for r in rows
                        if r.get("score") not in ("", None) and int(r["is_genuine"]) == 1])
    impostor = np.array([float(r["score"]) for r in rows
                         if r.get("score") not in ("", None) and int(r["is_genuine"]) == 0])
    return genuine, impostor


def threshold_at_far(impostor, far_target):
    """Lowest threshold whose false-accept rate is <= far_target.

    With N impostor scores the smallest measurable FAR is 1/N; asking for less returns
    the maximum impostor score and the caller should say so in the report.
    """
    if impostor.size == 0:
        return float("nan")
    ordered = np.sort(impostor)[::-1]
    allowed = int(np.floor(far_target * impostor.size))
    if allowed <= 0:
        return float(ordered[0]) + 1e-12      # nothing may be accepted
    return float(ordered[allowed - 1])


def tar_at_far(rows, far_target):
    genuine, impostor = scores_of(rows)
    if genuine.size == 0 or impostor.size == 0:
        return float("nan")
    threshold = threshold_at_far(impostor, far_target)
    return float(np.mean(genuine >= threshold))


def far_at_threshold(rows, threshold):
    _genuine, impostor = scores_of(rows)
    return float(np.mean(impostor >= threshold)) if impostor.size else float("nan")


def frr_at_threshold(rows, threshold, count_low_quality=True):
    """Rejected genuine attempts.

    A session that never produced an embedding (low_quality) is a genuine attempt that
    failed, so it counts — reporting FRR only over sessions that reached the matcher
    would quietly hide the frames the pipeline threw away.
    """
    genuine, _impostor = scores_of(rows)
    failures = int(np.sum(genuine < threshold))
    total = genuine.size
    if count_low_quality:
        low_quality = {r["probe_id"] for r in rows
                       if r.get("decision_input") == "low_quality"}
        failures += len(low_quality)
        total += len(low_quality)
    return float(failures) / total if total else float("nan")


def rank1(rows):
    """Share of probes whose highest-scoring gallery identity is the right one."""
    by_probe = {}
    for row in rows:
        if row.get("score") in ("", None):
            continue
        by_probe.setdefault(row["probe_id"], []).append(row)
    if not by_probe:
        return float("nan")
    correct = 0
    for candidates in by_probe.values():
        best = max(candidates, key=lambda r: float(r["score"]))
        correct += int(best["is_genuine"]) == 1
    return correct / float(len(by_probe))


def roc_points(rows, steps=512):
    """(far, tar, threshold) sampled over the observed score range."""
    genuine, impostor = scores_of(rows)
    if genuine.size == 0 or impostor.size == 0:
        return []
    lo = min(genuine.min(), impostor.min())
    hi = max(genuine.max(), impostor.max())
    points = []
    for threshold in np.linspace(hi, lo, steps):
        points.append((float(np.mean(impostor >= threshold)),
                       float(np.mean(genuine >= threshold)), float(threshold)))
    return points


def equal_error_rate(rows):
    """EER plus the threshold where FAR and FRR cross."""
    points = roc_points(rows)
    if not points:
        return float("nan"), float("nan")
    best = min(points, key=lambda p: abs(p[0] - (1.0 - p[1])))
    return (best[0] + (1.0 - best[1])) / 2.0, best[2]


def summarise(rows, far_targets=(1e-3, 1e-4), threshold=None, rounds=200):
    """Everything the recognition table in the report needs, with intervals."""
    genuine, impostor = scores_of(rows)
    result = {
        "n_probes": len({r["probe_id"] for r in rows}),
        "n_genuine": int(genuine.size),
        "n_impostor": int(impostor.size),
        "smallest_measurable_far": (1.0 / impostor.size) if impostor.size else float("nan"),
    }
    for far in far_targets:
        point, low, high = by_participant(rows, lambda r, f=far: tar_at_far(r, f),
                                          rounds=rounds)
        result["tar_at_far_{:g}".format(far)] = {"point": point, "low": low, "high": high,
                                                 "measurable": impostor.size * far >= 1}
    point, low, high = by_participant(rows, rank1, rounds=rounds)
    result["rank1"] = {"point": point, "low": low, "high": high}
    eer, eer_threshold = equal_error_rate(rows)
    result["eer"] = eer
    result["eer_threshold"] = eer_threshold
    if threshold is not None:
        result["at_threshold"] = {
            "threshold": threshold,
            "far": far_at_threshold(rows, threshold),
            "frr": frr_at_threshold(rows, threshold),
        }
    return result
