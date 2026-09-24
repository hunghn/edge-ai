# -*- coding: utf-8 -*-
"""Dataset tooling: the split must be by person, deterministic, and never leak."""
import csv
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "tools", "dataset"))

import split as split_tool  # noqa: E402


def manifest(tmp_path, participants=10, clips=3):
    path = tmp_path / "manifest.csv"
    with open(str(path), "w") as f:
        writer = csv.writer(f)
        writer.writerow(["clip", "participant_id", "session", "scenario", "is_attack"])
        for index in range(participants):
            pid = "P{:03d}".format(index + 1)
            for clip in range(clips):
                writer.writerow(["{}/{}.mp4".format(pid, clip), pid, 1, "normal", 0])
    return str(path)


def test_split_is_by_participant_and_disjoint(tmp_path):
    rows = split_tool.read_manifest(manifest(tmp_path))
    dev, test = split_tool.split(split_tool.participants(rows))
    assert set(dev) & set(test) == set()
    assert len(dev) + len(test) == 10
    assert len(dev) == 5


def test_split_is_deterministic(tmp_path):
    ids = split_tool.participants(split_tool.read_manifest(manifest(tmp_path)))
    assert split_tool.split(ids, seed=7) == split_tool.split(ids, seed=7)
    assert split_tool.split(ids, seed=7) != split_tool.split(ids, seed=8)


def test_every_clip_of_a_person_stays_on_one_side(tmp_path):
    """The point of splitting by person: no face may appear in both halves."""
    path = manifest(tmp_path, participants=6, clips=4)
    rows = split_tool.read_manifest(path)
    dev, test = split_tool.split(split_tool.participants(rows))
    for row in rows:
        in_dev = row["participant_id"] in dev
        in_test = row["participant_id"] in test
        assert in_dev != in_test


def test_split_cli_writes_json(tmp_path):
    path = manifest(tmp_path, participants=8)
    out = str(tmp_path / "split.json")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "dataset", "split.py"),
         "--manifest", path, "--out", out], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr.decode()
    with open(out) as f:
        payload = json.load(f)
    assert len(payload["dev"]) + len(payload["test"]) == 8
    assert payload["clips_per_participant"]["P001"] == 3


def test_empty_manifest_is_an_error(tmp_path):
    path = str(tmp_path / "empty.csv")
    with open(path, "w") as f:
        f.write("clip,participant_id\n")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, "tools", "dataset", "split.py"),
         "--manifest", path, "--out", str(tmp_path / "out.json")], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode != 0
    assert b"no participant_id" in result.stderr


def test_record_scenarios_cover_the_protocol():
    """The recorder must offer every condition the protocol promises."""
    import record

    names = {item["scenario"] for item in record.SCENARIOS}
    assert {"normal", "dark", "backlit", "near", "far", "turn", "nod", "glasses"} <= names
    assert {item["pai_type"] for item in record.ATTACKS} == {
        "print_matte", "print_glossy", "replay_phone", "replay_tablet"}
    # Every scenario has a Vietnamese instruction to read aloud.
    assert all(item["prompt"] for item in record.SCENARIOS)


def test_manifest_fields_carry_the_labels_m9_needs():
    import record

    for field in ("participant_id", "session", "scenario", "is_attack", "pai_type"):
        assert field in record.MANIFEST_FIELDS
    # No name, no birth date: participants are identified by code only.
    assert not {"full_name", "name", "birth_year"} & set(record.MANIFEST_FIELDS)
