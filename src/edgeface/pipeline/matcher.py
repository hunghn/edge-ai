"""S9: cosine matching against the gallery, with a per-frame vote.

Numbers are small by design (60 patients x 5 templates = 300 rows), so a brute-force
numpy product is both simplest and fastest; no index structure is warranted.

Everything a decision needs is returned, including the per-frame detail, so S10 does not
recompute anything and M9 can analyse the raw scores.
"""
from collections import namedtuple

import numpy as np

from edgeface.common.log import get_logger
from edgeface.common.timing import timed

LOG = get_logger("matcher")

MatchResult = namedtuple("MatchResult", [
    "top1_code", "top1_score", "top2_code", "top2_score", "margin",
    "votes", "k", "per_frame", "passed_threshold",
])

EMPTY = MatchResult(None, None, None, None, None, 0, 0, [], None)


def aggregate_per_patient(scores, owner, offsets, mode="max"):
    """(K, M) template scores -> (K, N) patient scores.

    Rows are grouped by patient, so reduceat walks each block once.
    """
    if scores.shape[1] == 0:
        return np.zeros((scores.shape[0], 0), dtype=np.float32)
    if mode == "max":
        return np.maximum.reduceat(scores, offsets, axis=1)
    if mode == "mean":
        sums = np.add.reduceat(scores, offsets, axis=1)
        counts = np.diff(np.concatenate([offsets, [scores.shape[1]]])).astype(np.float32)
        return sums / counts
    raise ValueError("unknown match.template_agg: {}".format(mode))


def _top2(row, codes):
    """(top1_code, top1_score, top2_code, top2_score) for one frame."""
    if row.shape[0] == 1:
        return codes[0], float(row[0]), None, None
    order = np.argsort(row)[::-1]
    return codes[order[0]], float(row[order[0]]), codes[order[1]], float(row[order[1]])


@timed("S9")
def match(embeddings, gallery, cfg):
    """Compare the session's embeddings with the gallery. Never raises on an empty one."""
    match_cfg = cfg["match"]
    vectors = [np.asarray(e.vector, dtype=np.float32) for e in embeddings]
    if not vectors or gallery.is_empty():
        return EMPTY._replace(k=len(vectors))

    scores = np.asarray(vectors, dtype=np.float32).dot(gallery.matrix.T)
    per_patient = aggregate_per_patient(scores, gallery.owner, gallery.group_offsets(),
                                        match_cfg.get("template_agg", "max"))

    per_frame = [_top2(row, gallery.codes) for row in per_patient]
    counts = {}
    for top1_code, top1_score, _, _ in per_frame:
        entry = counts.setdefault(top1_code, [0, 0.0])
        entry[0] += 1
        entry[1] += top1_score
    # Most votes wins; a tie goes to the higher mean score.
    winner = sorted(counts.items(), key=lambda kv: (kv[1][0], kv[1][1] / kv[1][0]))[-1][0]

    voting = [f for f in per_frame if f[0] == winner]
    top1_score = float(np.mean([f[1] for f in voting]))
    seconds = [f[3] for f in voting if f[3] is not None]
    top2_score = float(np.mean(seconds)) if seconds else None
    top2_codes = [f[2] for f in voting if f[2] is not None]
    top2_code = max(set(top2_codes), key=top2_codes.count) if top2_codes else None
    margin = None if top2_score is None else top1_score - top2_score

    threshold = match_cfg.get("threshold")
    margin_min = match_cfg.get("margin_top1_top2")
    votes = len(voting)
    if threshold is None or margin_min is None:
        passed = None                      # D-01/D-02 not calibrated yet: S10 decides
    else:
        passed = (votes >= match_cfg["vote_k"] and top1_score >= threshold
                  and (margin is None or margin >= margin_min))

    return MatchResult(top1_code=winner, top1_score=top1_score, top2_code=top2_code,
                       top2_score=top2_score, margin=margin, votes=votes,
                       k=len(vectors), per_frame=per_frame, passed_threshold=passed)


def best_match_for(vectors, gallery, cfg, exclude_code=None):
    """Highest-scoring patient for a set of vectors, used by the enrollment duplicate check."""
    if gallery.is_empty() or not len(vectors):
        return None, None
    scores = np.asarray(vectors, dtype=np.float32).dot(gallery.matrix.T)
    per_patient = aggregate_per_patient(scores, gallery.owner, gallery.group_offsets(),
                                        cfg["match"].get("template_agg", "max"))
    best_per_patient = per_patient.max(axis=0)
    if exclude_code is not None and exclude_code in gallery.codes:
        best_per_patient = best_per_patient.copy()
        best_per_patient[gallery.codes.index(exclude_code)] = -1.0
    index = int(np.argmax(best_per_patient))
    return gallery.codes[index], float(best_per_patient[index])
