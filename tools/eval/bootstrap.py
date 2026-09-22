# -*- coding: utf-8 -*-
"""Confidence intervals by bootstrapping over PEOPLE, not over comparisons.

Resampling individual comparisons would pretend that the twenty probes of one person are
twenty independent observations. They are not: they share a face, a haircut and a day.
Resampling participants keeps the correlation inside the resample, which is why every
interval in the report comes from here.
"""
import numpy as np

DEFAULT_ROUNDS = 1000
DEFAULT_SEED = 20260922


def by_participant(rows, statistic, rounds=DEFAULT_ROUNDS, seed=DEFAULT_SEED,
                   key="true_code", alpha=0.05):
    """(point, low, high) for `statistic(rows)`, resampling whole participants.

    Returns (point, nan, nan) when there are fewer than two participants: an interval
    from one person would be a lie dressed as a number.
    """
    groups = {}
    for row in rows:
        groups.setdefault(row[key], []).append(row)
    names = sorted(groups)
    point = statistic(rows)
    if len(names) < 2:
        return point, float("nan"), float("nan")

    rng = np.random.RandomState(seed)
    samples = []
    for _ in range(rounds):
        picked = rng.randint(0, len(names), size=len(names))
        resampled = []
        for index in picked:
            resampled.extend(groups[names[index]])
        value = statistic(resampled)
        if value is not None and np.isfinite(value):
            samples.append(value)
    if not samples:
        return point, float("nan"), float("nan")
    low = float(np.percentile(samples, 100 * alpha / 2))
    high = float(np.percentile(samples, 100 * (1 - alpha / 2)))
    return point, low, high


def format_interval(point, low, high, digits=4):
    if not np.isfinite(low) or not np.isfinite(high):
        return "{:.{d}f}".format(point, d=digits)
    return "{:.{d}f} [{:.{d}f}, {:.{d}f}]".format(point, low, high, d=digits)
