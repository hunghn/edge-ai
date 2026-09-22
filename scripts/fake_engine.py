# -*- coding: utf-8 -*-
"""Publish a scripted sequence of engine states, so the kiosk can be built and demoed
without a camera, models or a Nano.

  python3 scripts/fake_engine.py --config configs/dev.yaml --scenario identify
  python3 scripts/fake_engine.py --list

Scenarios live in tests/fixtures/kiosk_scenarios/*.yaml so the UI smoke test and a human
demo drive the kiosk through exactly the same steps.
"""
import argparse
import glob
import os
import sys
import time

import yaml

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.storage import clock, db, kiosk_ipc, patients  # noqa: E402

SCENARIO_DIR = os.path.join(REPO, "tests", "fixtures", "kiosk_scenarios")


def load_scenario(name):
    path = name if os.path.exists(name) else os.path.join(SCENARIO_DIR, name + ".yaml")
    with open(path) as f:
        return yaml.safe_load(f)


def list_scenarios():
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(SCENARIO_DIR, "*.yaml")))


def seed_patients(conn, rows, now):
    with db.transaction(conn):
        for row in rows or []:
            patients.upsert_patient(conn, row["patient_code"], row["full_name"],
                                    row.get("birth_year"), "kiosk", now)
            if row.get("appointment_code"):
                patients.upsert_appointment(conn, row["appointment_code"],
                                            row["patient_code"],
                                            clock.local_date(now))


def play(conn, scenario, speed=1.0, verbose=True):
    """Publish each step, honouring its `hold` duration. Returns the steps played."""
    now = clock.now()
    seed_patients(conn, scenario.get("patients"), now)
    session_id = scenario.get("session_id", "fake-session")
    played = []
    for step in scenario["steps"]:
        now = clock.now()
        payload = dict(step.get("payload") or {})
        if step["state"] == "AWAIT_NURSE" and "timeout_at" not in payload:
            payload["timeout_at"] = now + 30
        with db.transaction(conn):
            seq = kiosk_ipc.publish_state(conn, step["state"], step.get("guidance"),
                                          session_id, payload or None, now)
        played.append((seq, step["state"]))
        if verbose:
            print("  seq {:<3} {:<18} {}".format(seq, step["state"],
                                                 step.get("guidance") or ""))
        hold = float(step.get("hold", 1.0)) / max(speed, 1e-6)
        if hold > 0:
            time.sleep(hold)
    return played


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--scenario", default="identify")
    ap.add_argument("--speed", type=float, default=1.0, help="2.0 runs twice as fast")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for name in list_scenarios():
            print(name)
        return 0

    cfg = cfg_mod.load_config(args.config)
    db_path = cfg["storage"]["db_path"]
    conn = db.open_db(db_path if os.path.isabs(db_path) else os.path.join(REPO, db_path))
    scenario = load_scenario(args.scenario)
    try:
        while True:
            print("scenario:", scenario.get("name", args.scenario))
            play(conn, scenario, args.speed)
            if not args.loop:
                break
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
