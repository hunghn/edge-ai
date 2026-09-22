"""Enroll a patient from a recorded video, without a kiosk.

Used to build a gallery for offline evaluation (M8/M9) and to test the identification
path on a dev machine:

  python3 scripts/enroll_from_video.py --video bn001.mp4 --code BN001 --name "Nguyen Van A" \
      --config configs/dev.yaml [--birth-year 1990] [--appointment AP1] [--force]

It runs exactly the same gates as the kiosk, anti-spoofing included.
"""
import argparse
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.engine import enroll as enroll_mod  # noqa: E402
from edgeface.engine import loop as engine_loop  # noqa: E402
from edgeface.engine.models import close_models, load_models  # noqa: E402
from edgeface.gallery.gallery import Gallery  # noqa: E402
from edgeface.pipeline import best_frame as bf  # noqa: E402
from edgeface.pipeline.capture import FileSource  # noqa: E402
from edgeface.storage import clock, db  # noqa: E402
from edgeface.types import Frame  # noqa: E402


def collect(video, models, cfg, wanted, min_interval_s, verbose=True):
    """Run the pipeline until `wanted` good embeddings are spaced far enough apart."""
    collector = engine_loop.new_collector(cfg)
    source = FileSource(video).open()
    kept, last_ts, index, stops = [], None, 0, {}
    try:
        while len(kept) < wanted:
            image = source.read()
            if image is None:
                break
            index += 1
            ts = index / 15.0
            outcome = engine_loop.process_frame(Frame(index, ts, image), models, cfg, collector)
            if outcome.guidance is not None:
                stops[outcome.guidance] = stops.get(outcome.guidance, 0) + 1
                continue
            if last_ts is not None and (ts - last_ts) < min_interval_s:
                continue
            kept.append(outcome.obs.embedding)
            last_ts = ts
            if verbose:
                print("  captured {}/{} at frame {}".format(len(kept), wanted, index))
            collector.reset(bf.RESET_CONSUMED)
    finally:
        source.release()
    return kept, index, stops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--video", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--birth-year", type=int)
    ap.add_argument("--appointment")
    ap.add_argument("--force", action="store_true", help="save despite a duplicate warning")
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    db_path = cfg["storage"]["db_path"]
    conn = db.open_db(db_path if os.path.isabs(db_path) else os.path.join(REPO, db_path))
    models = load_models(cfg, strict=False)
    try:
        wanted = cfg["enroll"]["num_templates"]
        embeddings, frames, stops = collect(args.video, models, cfg, wanted,
                                            cfg["enroll"]["min_interval_s"])
        if len(embeddings) < wanted:
            print("only {}/{} usable frames in {} ({} frames read)".format(
                len(embeddings), wanted, args.video, frames))
            print("rejections:", stops)
            return 1

        form = {"patient_code": args.code, "full_name": args.name,
                "birth_year": args.birth_year, "appointment_code": args.appointment}
        ok, reason = enroll_mod.validate_form(form)
        if not ok:
            print("invalid form:", reason)
            return 2

        gallery = Gallery(models["recognizer_sha256"]).load(conn, clock.now())
        review = enroll_mod.review(form, embeddings, gallery, cfg)
        print("self-consistency: {}".format(
            "n/a" if review.self_consistency is None else round(review.self_consistency, 4)))
        if review.duplicate_code:
            print("closest existing patient: {} at {:.4f}".format(
                review.duplicate_code, review.duplicate_score))
        if review.warnings:
            print("warnings:", review.warnings)
        if review.blocked and not args.force:
            print("refused: duplicate_policy is 'block' (use --force to override)")
            return 3
        if "duplicate_face" in review.warnings and not args.force:
            print("refused: this face already belongs to {} (use --force if they differ)".format(
                review.duplicate_code))
            return 3

        result = enroll_mod.commit(conn, form, embeddings, cfg, models["recognizer_sha256"])
        print("enrolled {}: {} templates, gallery v{}".format(
            result["patient_code"], result["n_templates"], result["gallery_version"]))
        return 0
    finally:
        close_models(models)
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
