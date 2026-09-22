# -*- coding: utf-8 -*-
"""Build an evaluation gallery database from enrolment clips.

  python tools/dataset/build_gallery.py --clips "data/enroll/*.mp4" --db var/eval.db

One clip per identity, named after the patient code. Uses the same enrolment path as the
kiosk (same gates, same anti-spoofing), so the gallery under test is the gallery the
clinic would actually have.
"""
import argparse
import glob
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "scripts"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.engine import enroll as enroll_mod  # noqa: E402
from edgeface.engine.models import close_models, load_models  # noqa: E402
from edgeface.storage import clock, db, patients, templates  # noqa: E402


def main():
    from enroll_from_video import collect

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--clips", nargs="+", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--ttl-hours", type=float, default=24 * 365,
                    help="evaluation galleries should outlive the 24 h kiosk TTL")
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    conn = db.open_db(args.db)
    models = load_models(cfg, strict=False)
    wanted = cfg["enroll"]["num_templates"]
    now = clock.now()

    paths = []
    for pattern in args.clips:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])

    enrolled, skipped = 0, []
    try:
        for path in paths:
            code = os.path.splitext(os.path.basename(path))[0]
            embeddings, frames, stops = collect(path, models, cfg, wanted,
                                                cfg["enroll"]["min_interval_s"],
                                                verbose=False)
            if len(embeddings) < wanted:
                skipped.append((code, len(embeddings), stops))
                print("  {}: only {}/{} usable frames — skipped ({})".format(
                    code, len(embeddings), wanted, stops))
                continue
            with db.transaction(conn):
                patients.upsert_patient(conn, code, code, None, patients.SOURCE_KIOSK,
                                        now, args.ttl_hours)
                templates.add_templates(conn, code, [e.vector for e in embeddings],
                                        models["recognizer_sha256"],
                                        [e.quality for e in embeddings], now)
            enrolled += 1
            print("  {}: {} templates".format(code, len(embeddings)))
    finally:
        close_models(models)
        conn.close()
    print("gallery: {} identities enrolled, {} skipped -> {}".format(
        enrolled, len(skipped), args.db))
    return 0 if enrolled else 1


if __name__ == "__main__":
    sys.exit(main())
