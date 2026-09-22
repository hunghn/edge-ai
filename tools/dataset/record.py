# -*- coding: utf-8 -*-
"""Record dataset clips on the kiosk itself, one scenario at a time.

  python3 tools/dataset/record.py --participant P001 --session 1 --out data/raw

Runs on the Nano so the clips come from the camera, the lens and the lighting that the
system will actually face. It prompts for each scenario in the protocol, records a clip,
and appends a row to manifest.csv.

Consent: the participant id is a code, never a name. The code-to-person mapping stays on
paper with the signed consent form (docs/dataset/phieu_dong_y.md) — not in this repo and
not in the manifest.
"""
import argparse
import csv
import os
import sys
import time

import cv2

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.pipeline.capture import source_from_config  # noqa: E402

MANIFEST_FIELDS = ["clip", "participant_id", "session", "scenario", "lighting", "distance",
                   "pose", "glasses", "is_attack", "pai_type", "frames", "recorded_at"]

# The scenario matrix of docs/dataset/protocol.md (D-28 — confirm before a real shoot).
SCENARIOS = [
    {"scenario": "normal", "lighting": "room", "distance": "standard", "pose": "front",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Đứng thẳng, nhìn vào camera, ánh sáng phòng bình thường"},
    {"scenario": "dark", "lighting": "dim", "distance": "standard", "pose": "front",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Tắt bớt đèn, đứng như cũ"},
    {"scenario": "backlit", "lighting": "backlit", "distance": "standard", "pose": "front",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Đứng quay lưng về phía cửa sổ (ngược sáng)"},
    {"scenario": "near", "lighting": "room", "distance": "near", "pose": "front",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Đứng gần hơn bình thường một bước"},
    {"scenario": "far", "lighting": "room", "distance": "far", "pose": "front",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Lùi ra xa tới giới hạn vẫn nhận được"},
    {"scenario": "turn", "lighting": "room", "distance": "standard", "pose": "turned",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Quay mặt sang trái rồi sang phải khoảng 20 độ"},
    {"scenario": "nod", "lighting": "room", "distance": "standard", "pose": "nodding",
     "glasses": "no", "is_attack": 0, "pai_type": "", "prompt":
     "Cúi nhẹ rồi ngửa nhẹ"},
    {"scenario": "glasses", "lighting": "room", "distance": "standard", "pose": "front",
     "glasses": "yes", "is_attack": 0, "pai_type": "", "prompt":
     "Đeo kính (nếu có), đứng thẳng"},
]

ATTACKS = [
    {"scenario": "attack_print_matte", "pai_type": "print_matte"},
    {"scenario": "attack_print_glossy", "pai_type": "print_glossy"},
    {"scenario": "attack_phone", "pai_type": "replay_phone"},
    {"scenario": "attack_tablet", "pai_type": "replay_tablet"},
]


def record_clip(source, path, seconds, fps=15.0, preview=False):
    """Record one clip; returns the number of frames written."""
    writer, frames = None, 0
    deadline = time.time() + seconds
    while time.time() < deadline:
        image = source.read()
        if image is None:
            continue
        if writer is None:
            height, width = image.shape[:2]
            writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps,
                                     (width, height))
        writer.write(image)
        frames += 1
        if preview:
            cv2.imshow("recording", image)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    if writer is not None:
        writer.release()
    if preview:
        cv2.destroyAllWindows()
    return frames


def append_manifest(path, row):
    exists = os.path.exists(path)
    with open(path, "a") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    ap.add_argument("--participant", required=True, help="code such as P001, never a name")
    ap.add_argument("--session", type=int, required=True, help="1 = enrol day, 2 = probe day")
    ap.add_argument("--out", default=os.path.join(REPO, "data", "raw"))
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--attacks", action="store_true", help="record the presentation attacks")
    ap.add_argument("--only", help="record a single scenario by name")
    ap.add_argument("--preview", action="store_true")
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    directory = os.path.join(args.out, args.participant)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    manifest = os.path.join(args.out, "manifest.csv")

    plan = list(SCENARIOS)
    if args.attacks:
        for attack in ATTACKS:
            plan.append(dict(SCENARIOS[0], scenario=attack["scenario"],
                             pai_type=attack["pai_type"], is_attack=1,
                             prompt="Giơ {} trước camera ở khoảng cách thường".format(
                                 attack["pai_type"])))
    if args.only:
        plan = [item for item in plan if item["scenario"] == args.only]
        if not plan:
            raise SystemExit("unknown scenario: " + args.only)

    source = source_from_config(cfg).open()
    try:
        for item in plan:
            name = "{}_s{}_{}.mp4".format(args.participant, args.session, item["scenario"])
            path = os.path.join(directory, name)
            print("\n=== {} ===".format(item["scenario"]))
            print("    {}".format(item["prompt"]))
            input("    Nhấn Enter để bắt đầu ghi {:.0f} giây...".format(args.seconds))
            frames = record_clip(source, path, args.seconds, cfg["capture"].get("fps", 15),
                                 args.preview)
            append_manifest(manifest, {
                "clip": os.path.relpath(path, args.out), "participant_id": args.participant,
                "session": args.session, "scenario": item["scenario"],
                "lighting": item["lighting"], "distance": item["distance"],
                "pose": item["pose"], "glasses": item["glasses"],
                "is_attack": item["is_attack"], "pai_type": item["pai_type"],
                "frames": frames, "recorded_at": time.time()})
            print("    đã ghi {} frame -> {}".format(frames, path))
    finally:
        source.release()
    print("\nmanifest:", manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
