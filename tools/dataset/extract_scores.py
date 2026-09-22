# -*- coding: utf-8 -*-
"""Run the main pipeline over probe clips and write the score table M9 consumes.

  python tools/dataset/extract_scores.py --gallery-db var/eval.db --probes "data/probe/*.mp4" \
      --config configs/dev.yaml --out results/scores_pipeline.csv

One row per (probe session, gallery patient): genuine when the identity matches. That
shape is what makes TAR@FAR computable — a table of only top-1 answers cannot produce a
FAR curve, because the impostor scores are exactly the ones a top-1 table throws away.
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))

from edgeface import config as cfg_mod  # noqa: E402
from edgeface.engine import loop as engine_loop  # noqa: E402
from edgeface.engine.models import close_models, load_models  # noqa: E402
from edgeface.gallery.gallery import Gallery  # noqa: E402
from edgeface.pipeline import best_frame as bf  # noqa: E402
from edgeface.pipeline import matcher  # noqa: E402
from edgeface.pipeline.capture import FileSource  # noqa: E402
from edgeface.storage import clock, db  # noqa: E402
from edgeface.types import Frame  # noqa: E402

FIELDS = ["probe_id", "true_code", "claimed_code", "score", "is_genuine", "system",
          "votes", "k", "n_good_frames", "min_p_real", "decision_input", "clip"]


def code_of(path):
    return os.path.splitext(os.path.basename(path))[0].split("_")[0]


def sessions_from_clip(path, models, cfg, max_sessions=0):
    """Replay a clip and yield each collected batch of embeddings, like a real visit."""
    collector = engine_loop.new_collector(cfg)
    source = FileSource(path).open()
    index, produced = 0, 0
    spoof_frames, min_p_real = 0, None
    try:
        while True:
            image = source.read()
            if image is None:
                break
            index += 1
            outcome = engine_loop.process_frame(Frame(index, index / 15.0, image),
                                                models, cfg, collector)
            if outcome.guidance == "SPOOF_SUSPECT":
                spoof_frames += 1
                if outcome.obs.spoof is not None:
                    p = outcome.obs.spoof.p_real
                    min_p_real = p if min_p_real is None else min(min_p_real, p)
            if outcome.collector == bf.READY:
                status, embeddings, n_good = collector.result(index / 15.0)
                yield embeddings, n_good, spoof_frames, min_p_real
                produced += 1
                collector.reset(bf.RESET_CONSUMED)
                spoof_frames, min_p_real = 0, None
                if max_sessions and produced >= max_sessions:
                    break
            elif outcome.collector == bf.LOW_QUALITY:
                yield [], collector.n_good, spoof_frames, min_p_real
                produced += 1
                collector.reset(bf.RESET_CONSUMED)
                spoof_frames, min_p_real = 0, None
    finally:
        source.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "dev.yaml"))
    ap.add_argument("--gallery-db", required=True, help="database built by build_gallery.py")
    ap.add_argument("--probes", nargs="+", required=True)
    ap.add_argument("--out", default=os.path.join(REPO, "results", "scores_pipeline.csv"))
    ap.add_argument("--max-sessions", type=int, default=0, help="per clip; 0 = all")
    args = ap.parse_args()

    cfg = cfg_mod.load_config(args.config)
    conn = db.open_db(args.gallery_db)
    models = load_models(cfg, strict=False)
    gallery = Gallery(models["recognizer_sha256"]).load(conn, clock.now())
    if gallery.is_empty():
        raise SystemExit("gallery is empty — run tools/dataset/build_gallery.py first")

    paths = []
    for pattern in args.probes:
        paths.extend(sorted(glob.glob(pattern)) or [pattern])
    directory = os.path.dirname(args.out)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    written, low_quality = 0, 0
    try:
        with open(args.out, "w") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            for path in paths:
                true_code = code_of(path)
                for number, (embeddings, n_good, spoof_frames, min_p_real) in enumerate(
                        sessions_from_clip(path, models, cfg, args.max_sessions)):
                    probe_id = "{}#{}".format(os.path.basename(path), number)
                    if not embeddings:
                        low_quality += 1
                        writer.writerow({"probe_id": probe_id, "true_code": true_code,
                                         "claimed_code": "", "score": "", "is_genuine": "",
                                         "system": "edgeface", "votes": 0, "k": 0,
                                         "n_good_frames": n_good, "min_p_real": min_p_real,
                                         "decision_input": "low_quality", "clip": path})
                        continue
                    result = matcher.match(embeddings, gallery, cfg)
                    vectors = np.asarray([e.vector for e in embeddings], dtype=np.float32)
                    per_patient = matcher.aggregate_per_patient(
                        vectors.dot(gallery.matrix.T), gallery.owner,
                        gallery.group_offsets(), cfg["match"].get("template_agg", "max"))
                    session_scores = per_patient.max(axis=0)   # best frame per patient
                    for code, score in zip(gallery.codes, session_scores):
                        writer.writerow({
                            "probe_id": probe_id, "true_code": true_code,
                            "claimed_code": code, "score": round(float(score), 6),
                            "is_genuine": int(code == true_code), "system": "edgeface",
                            "votes": result.votes if code == result.top1_code else "",
                            "k": result.k, "n_good_frames": n_good,
                            "min_p_real": min_p_real, "decision_input": "ready",
                            "clip": path})
                        written += 1
    finally:
        close_models(models)
        conn.close()
    print("wrote {} comparison rows ({} low-quality sessions) to {}".format(
        written, low_quality, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
