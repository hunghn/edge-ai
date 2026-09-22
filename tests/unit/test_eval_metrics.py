# -*- coding: utf-8 -*-
"""Evaluation metrics against cases whose answer is known in advance.

A metric tool that is only ever run on real data cannot be checked: you would be
comparing an unknown number with an unknown number. So every metric here is exercised on
distributions whose value can be derived by hand or analytically.
"""
import math

import numpy as np
import pytest

from tools.eval import antispoof, recognition
from tools.eval.bootstrap import by_participant, format_interval


def comparison_rows(genuine_scores, impostor_scores, participant="P001", probe="p1"):
    rows = [{"probe_id": probe, "true_code": participant, "claimed_code": participant,
             "score": str(score), "is_genuine": "1", "decision_input": "ready"}
            for score in genuine_scores]
    rows += [{"probe_id": probe, "true_code": participant, "claimed_code": "OTHER",
              "score": str(score), "is_genuine": "0", "decision_input": "ready"}
             for score in impostor_scores]
    return rows


# ---------------------------------------------------------------- TAR / FAR
def test_threshold_at_far_picks_the_right_score():
    impostor = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    # 10 impostors, FAR 0.1 -> exactly one may be accepted -> the largest one.
    assert recognition.threshold_at_far(impostor, 0.1) == pytest.approx(1.0)
    assert recognition.threshold_at_far(impostor, 0.3) == pytest.approx(0.8)
    # A FAR below 1/N cannot be measured: nothing may be accepted.
    assert recognition.threshold_at_far(impostor, 0.01) > 1.0


def test_tar_at_far_on_a_hand_checkable_case():
    genuine = [0.95, 0.9, 0.85, 0.5]
    impostor = [0.1, 0.2, 0.3, 0.4, 0.45, 0.6, 0.7, 0.8, 0.88, 0.92]
    rows = comparison_rows(genuine, impostor)
    # FAR 0.1 -> threshold 0.92 -> only 0.95 passes -> TAR 1/4.
    assert recognition.tar_at_far(rows, 0.1) == pytest.approx(0.25)
    # FAR 0.3 -> threshold 0.8 -> 0.95, 0.9, 0.85 pass -> 3/4.
    assert recognition.tar_at_far(rows, 0.3) == pytest.approx(0.75)


def test_tar_matches_the_analytic_value_for_gaussians():
    """Separated Gaussians have a TAR@FAR that can be computed in closed form."""
    rng = np.random.RandomState(0)
    genuine = rng.normal(1.0, 0.25, size=20000)
    impostor = rng.normal(0.0, 0.25, size=20000)
    rows = comparison_rows(genuine, impostor)
    far = 0.01
    # threshold = impostor mean + z * sigma; TAR = P(genuine >= threshold)
    z = 2.3263478740408408                      # Phi^-1(0.99)
    threshold = 0.0 + z * 0.25
    expected = 0.5 * math.erfc((threshold - 1.0) / (0.25 * math.sqrt(2)))
    assert recognition.tar_at_far(rows, far) == pytest.approx(expected, abs=0.01)


def test_far_and_frr_at_a_threshold():
    rows = comparison_rows([0.9, 0.8, 0.4], [0.1, 0.5, 0.85])
    assert recognition.far_at_threshold(rows, 0.6) == pytest.approx(1 / 3)
    assert recognition.frr_at_threshold(rows, 0.6, count_low_quality=False) == pytest.approx(
        1 / 3)


def test_frr_counts_low_quality_sessions():
    """A session that never reached the matcher is still a failed genuine attempt."""
    rows = comparison_rows([0.9, 0.8], [0.1])
    rows.append({"probe_id": "p2", "true_code": "P001", "claimed_code": "",
                 "score": "", "is_genuine": "", "decision_input": "low_quality"})
    assert recognition.frr_at_threshold(rows, 0.5, count_low_quality=False) == 0.0
    assert recognition.frr_at_threshold(rows, 0.5) == pytest.approx(1 / 3)


def test_rank1_picks_the_best_scoring_identity():
    rows = [
        {"probe_id": "a", "true_code": "P1", "claimed_code": "P1", "score": "0.9",
         "is_genuine": "1"},
        {"probe_id": "a", "true_code": "P1", "claimed_code": "P2", "score": "0.5",
         "is_genuine": "0"},
        {"probe_id": "b", "true_code": "P2", "claimed_code": "P1", "score": "0.8",
         "is_genuine": "0"},
        {"probe_id": "b", "true_code": "P2", "claimed_code": "P2", "score": "0.6",
         "is_genuine": "1"},
    ]
    assert recognition.rank1(rows) == pytest.approx(0.5)


def test_eer_of_symmetric_distributions():
    rng = np.random.RandomState(1)
    rows = comparison_rows(rng.normal(1.0, 0.5, 5000), rng.normal(0.0, 0.5, 5000))
    eer, threshold = recognition.equal_error_rate(rows)
    assert eer == pytest.approx(0.1587, abs=0.01)    # Phi(-1) for 1 sigma separation
    assert threshold == pytest.approx(0.5, abs=0.05)


def test_roc_is_monotonic():
    rng = np.random.RandomState(2)
    rows = comparison_rows(rng.normal(1.0, 0.4, 500), rng.normal(0.0, 0.4, 500))
    points = recognition.roc_points(rows, steps=50)
    fars = [p[0] for p in points]
    tars = [p[1] for p in points]
    assert fars == sorted(fars) and tars == sorted(tars)


def test_summary_flags_an_unmeasurable_far():
    """With 100 impostor comparisons, FAR=1e-4 is not measurable — say so."""
    rng = np.random.RandomState(3)
    rows = comparison_rows(rng.normal(1.0, 0.3, 50), rng.normal(0.0, 0.3, 100))
    summary = recognition.summarise(rows, far_targets=(1e-2, 1e-4), rounds=20)
    assert summary["tar_at_far_0.01"]["measurable"] is True
    assert summary["tar_at_far_0.0001"]["measurable"] is False
    assert summary["smallest_measurable_far"] == pytest.approx(0.01)


# ---------------------------------------------------------------- anti-spoofing
def pad_rows(real_scores, attacks):
    rows = [{"p_real": str(s), "is_attack": 0, "pai_type": "", "true_code": "P001"}
            for s in real_scores]
    for pai_type, scores in attacks.items():
        rows += [{"p_real": str(s), "is_attack": 1, "pai_type": pai_type,
                  "true_code": "P001"} for s in scores]
    return rows


def test_apcer_is_the_worst_species_not_the_average():
    rows = pad_rows([0.95, 0.9], {"print_matte": [0.1, 0.2],          # 0% accepted
                                  "replay_phone": [0.9, 0.95, 0.99]})  # 100% accepted
    by_species = antispoof.apcer_by_species(rows, threshold=0.85)
    assert by_species == {"print_matte": 0.0, "replay_phone": 1.0}
    assert antispoof.apcer(rows, 0.85) == pytest.approx(1.0)     # the one that works
    assert antispoof.apcer_mean(rows, 0.85) == pytest.approx(0.5)


def test_bpcer_and_acer():
    rows = pad_rows([0.95, 0.9, 0.5, 0.4], {"print_matte": [0.1, 0.9]})
    assert antispoof.bpcer(rows, 0.85) == pytest.approx(0.5)     # 2 of 4 real rejected
    assert antispoof.apcer(rows, 0.85) == pytest.approx(0.5)     # 1 of 2 attacks accepted
    assert antispoof.acer(rows, 0.85) == pytest.approx(0.5)


def test_bpcer_at_a_target_apcer():
    rng = np.random.RandomState(4)
    rows = pad_rows(rng.normal(0.9, 0.05, 300),
                    {"print": rng.normal(0.2, 0.1, 300)})
    bpcer, threshold = antispoof.bpcer_at_apcer(rows, 0.05)
    assert 0.0 <= bpcer <= 1.0 and np.isfinite(threshold)


def test_pad_summary_shape():
    rows = pad_rows([0.9, 0.95], {"print": [0.1], "replay": [0.88]})
    summary = antispoof.summarise(rows, threshold=0.85, rounds=20)
    assert summary["n_real"] == 2 and summary["n_attack"] == 2
    assert set(summary["apcer_by_species"]) == {"print", "replay"}
    assert summary["acer"] == pytest.approx(
        (summary["apcer"]["point"] + summary["bpcer"]["point"]) / 2)


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_resamples_participants_not_rows():
    """Two participants, opposite outcomes: the interval must span both."""
    rows = ([{"true_code": "P1", "value": 1.0}] * 20
            + [{"true_code": "P2", "value": 0.0}] * 20)
    statistic = lambda r: float(np.mean([x["value"] for x in r]))  # noqa: E731
    point, low, high = by_participant(rows, statistic, rounds=500)
    assert point == pytest.approx(0.5)
    assert low == pytest.approx(0.0, abs=1e-9) and high == pytest.approx(1.0, abs=1e-9)


def test_bootstrap_is_deterministic():
    rows = [{"true_code": "P{}".format(i % 5), "value": i} for i in range(50)]
    statistic = lambda r: float(np.mean([x["value"] for x in r]))  # noqa: E731
    assert by_participant(rows, statistic, rounds=100) == by_participant(
        rows, statistic, rounds=100)


def test_bootstrap_refuses_an_interval_from_one_person():
    rows = [{"true_code": "P1", "value": 1.0}] * 10
    point, low, high = by_participant(rows, lambda r: 1.0, rounds=100)
    assert point == 1.0 and math.isnan(low) and math.isnan(high)
    assert format_interval(point, low, high) == "1.0000"
