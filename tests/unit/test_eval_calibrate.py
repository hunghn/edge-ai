# -*- coding: utf-8 -*-
"""The calibration tool: it must refuse to tune on the test split, and it must only
ever propose. Thresholds reach configs/default.yaml when a person puts them there."""
import csv
import json
import os
import subprocess
import sys

import numpy as np
import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

from tools.eval import calibrate  # noqa: E402

CALIBRATE = os.path.join(REPO, "tools", "eval", "calibrate.py")


def write_scores(path, participants=("P1", "P2", "P3", "P4"), seed=0):
    """A comparison table with a clear genuine/impostor separation."""
    rng = np.random.RandomState(seed)
    with open(path, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["probe_id", "true_code", "claimed_code", "score", "is_genuine",
                         "system", "decision_input"])
        for person in participants:
            for probe in range(5):
                probe_id = "{}#{}".format(person, probe)
                for other in participants:
                    genuine = int(other == person)
                    score = rng.normal(0.8 if genuine else 0.3, 0.05)
                    writer.writerow([probe_id, person, other, round(score, 5), genuine,
                                     "edgeface", "ready"])
    return path


def write_split(path, dev, test):
    with open(path, "w") as f:
        json.dump({"dev": dev, "test": test}, f)
    return path


def test_refuses_to_calibrate_on_test_participants(tmp_path):
    scores = write_scores(str(tmp_path / "scores.csv"))
    split = write_split(str(tmp_path / "split.json"), dev=["P1", "P2"], test=["P3", "P4"])
    result = subprocess.run(
        [sys.executable, CALIBRATE, "--scores", scores, "--split", split,
         "--out", str(tmp_path / "out.md")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode != 0
    message = result.stderr.decode()
    assert "TEST split" in message and "P3" in message


def test_accepts_dev_only_scores(tmp_path):
    scores = write_scores(str(tmp_path / "scores.csv"), participants=("P1", "P2"))
    split = write_split(str(tmp_path / "split.json"), dev=["P1", "P2"], test=["P3"])
    out = str(tmp_path / "proposal.md")
    result = subprocess.run(
        [sys.executable, CALIBRATE, "--scores", scores, "--split", split,
         "--far", "0.1", "--out", out], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode()
    with open(out) as f:
        text = f.read()
    assert "match.threshold" in text and "chờ duyệt" in text


def test_the_proposal_does_not_touch_the_config(tmp_path):
    """The whole point: a machine proposes, a person decides."""
    config_before = open(os.path.join(REPO, "configs", "default.yaml")).read()
    scores = write_scores(str(tmp_path / "scores.csv"), participants=("P1", "P2"))
    subprocess.run([sys.executable, CALIBRATE, "--scores", scores, "--far", "0.1",
                    "--out", str(tmp_path / "p.md")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert open(os.path.join(REPO, "configs", "default.yaml")).read() == config_before
    # and the thresholds are still null, waiting for a human
    assert "threshold: null" in config_before


def test_margin_sweep_trades_recall_for_precision(tmp_path):
    rows = list(csv.DictReader(open(write_scores(str(tmp_path / "s.csv")))))
    table, best = calibrate.margin_sweep(rows, threshold=0.0, frr_budget=0.05)
    assert table and best is not None
    kept = [row[1] for row in table]
    assert kept == sorted(kept, reverse=True)      # a larger margin keeps fewer probes
    assert (1.0 - best[1]) <= 0.05                 # and stays inside the budget


def test_margin_sweep_with_a_single_gallery_entry(tmp_path):
    """One identity means no second-best score; the sweep must not divide by nothing."""
    rows = list(csv.DictReader(open(write_scores(str(tmp_path / "s.csv"),
                                                 participants=("P1",)))))
    table, best = calibrate.margin_sweep(rows, threshold=0.0, frr_budget=0.05)
    assert table and best is not None


def test_missing_scores_file_is_reported(tmp_path):
    result = subprocess.run([sys.executable, CALIBRATE, "--scores",
                             str(tmp_path / "nope.csv")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode != 0
