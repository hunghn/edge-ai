# -*- coding: utf-8 -*-
"""Split participants into dev and test — by person, never by clip.

  python tools/dataset/split.py --manifest data/manifest.csv --out data/split.json

Splitting by clip would put the same face on both sides, and every threshold calibrated
on dev would then be tuned on people who also appear in the test set. M9 refuses to
calibrate on anything listed in the test split.
"""
import argparse
import collections
import csv
import json
import os
import random
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def read_manifest(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def participants(rows):
    return sorted({row["participant_id"] for row in rows if row.get("participant_id")})


def split(ids, dev_fraction=0.5, seed=20260922):
    """Deterministic split: the same manifest always gives the same two groups."""
    shuffled = list(ids)
    random.Random(seed).shuffle(shuffled)
    cut = int(round(len(shuffled) * dev_fraction))
    dev, test = sorted(shuffled[:cut]), sorted(shuffled[cut:])
    return dev, test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", default=os.path.join(REPO, "data", "split.json"))
    ap.add_argument("--dev-fraction", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=20260922)
    args = ap.parse_args()

    rows = read_manifest(args.manifest)
    ids = participants(rows)
    if not ids:
        raise SystemExit("no participant_id column values in " + args.manifest)
    dev, test = split(ids, args.dev_fraction, args.seed)

    counts = collections.Counter(row["participant_id"] for row in rows)
    payload = {"seed": args.seed, "dev_fraction": args.dev_fraction,
               "dev": dev, "test": test,
               "clips_per_participant": {pid: counts[pid] for pid in ids}}
    with open(args.out, "w") as f:
        json.dump(payload, f, indent=2)
    print("dev: {} participants, test: {}".format(len(dev), len(test)))
    print("wrote", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
