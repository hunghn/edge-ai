import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.gallery.gallery import Gallery
from edgeface.pipeline import matcher
from edgeface.storage import db, patients, templates
from edgeface.types import Embedding

SHA = "sha-model-a"
T0 = 1_700_000_000.0


@pytest.fixture
def cfg(repo_root):
    import os
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def unit(seed):
    rng = np.random.RandomState(seed)
    v = rng.randn(512).astype(np.float32)
    return v / np.linalg.norm(v)


def noisy(vector, sigma, seed):
    """A unit vector `sigma` away from `vector` in cosine terms.

    The noise is scaled by 1/sqrt(dim): a per-dimension sigma of 0.2 over 512 dimensions
    would have norm ~4.5 and drown the signal entirely.
    """
    rng = np.random.RandomState(seed)
    out = vector + rng.randn(512).astype(np.float32) * (sigma / np.sqrt(512.0))
    return (out / np.linalg.norm(out)).astype(np.float32)


def emb(vector, i=0):
    return Embedding(frame_id=i, ts=float(i), vector=vector, quality=None, raw_norm=20.0)


def enroll(conn, code, vectors, at=T0):
    with db.transaction(conn):
        patients.upsert_patient(conn, code, code, 1990, "kiosk", at)
        templates.add_templates(conn, code, vectors, SHA, created_at=at)


def loaded_gallery(conn):
    return Gallery(SHA).load(conn, now=T0)


def test_empty_gallery_is_not_an_error(conn, cfg):
    result = matcher.match([emb(unit(1))], loaded_gallery(conn), cfg)
    assert result.top1_code is None and result.votes == 0 and result.k == 1


def test_no_embeddings(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    assert matcher.match([], loaded_gallery(conn), cfg).top1_code is None


def test_matches_the_right_patient(conn, cfg):
    enroll(conn, "BN001", [unit(1), unit(2)])
    enroll(conn, "BN002", [unit(3)])
    enroll(conn, "BN003", [unit(4)])
    probes = [emb(noisy(unit(3), 0.2, s), s) for s in range(5)]
    result = matcher.match(probes, loaded_gallery(conn), cfg)
    assert result.top1_code == "BN002"
    assert result.votes == 5 and result.k == 5
    assert result.top1_score > result.top2_score and result.margin > 0
    assert len(result.per_frame) == 5


def test_vote_beats_a_single_odd_frame(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    enroll(conn, "BN002", [unit(2)])
    probes = [emb(noisy(unit(2), 0.1, s), s) for s in range(4)]
    probes.append(emb(unit(1), 4))            # one frame votes for the other patient
    result = matcher.match(probes, loaded_gallery(conn), cfg)
    assert result.top1_code == "BN002" and result.votes == 4
    # the odd frame is still visible in the detail for analysis
    assert [f[0] for f in result.per_frame].count("BN001") == 1


def test_template_aggregation_max_vs_mean(conn, cfg):
    """One good template plus one bad one: max keeps the patient, mean dilutes them."""
    enroll(conn, "BN001", [unit(1), unit(99)])
    gallery = loaded_gallery(conn)
    probe = [emb(noisy(unit(1), 0.1, 5))]

    max_cfg = dict(cfg)
    max_cfg["match"] = dict(cfg["match"], template_agg="max")
    mean_cfg = dict(cfg)
    mean_cfg["match"] = dict(cfg["match"], template_agg="mean")
    assert (matcher.match(probe, gallery, max_cfg).top1_score
            > matcher.match(probe, gallery, mean_cfg).top1_score)
    with pytest.raises(ValueError):
        bad = dict(cfg)
        bad["match"] = dict(cfg["match"], template_agg="median")
        matcher.match(probe, gallery, bad)


def test_passed_threshold_is_none_until_calibrated(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    probes = [emb(noisy(unit(1), 0.1, s), s) for s in range(5)]
    assert cfg["match"]["threshold"] is None
    assert matcher.match(probes, loaded_gallery(conn), cfg).passed_threshold is None

    calibrated = dict(cfg)
    calibrated["match"] = dict(cfg["match"], threshold=0.3, margin_top1_top2=0.0)
    assert matcher.match(probes, loaded_gallery(conn), calibrated).passed_threshold is True

    strict = dict(cfg)
    strict["match"] = dict(cfg["match"], threshold=0.999, margin_top1_top2=0.0)
    assert matcher.match(probes, loaded_gallery(conn), strict).passed_threshold is False


def test_votes_below_vote_k_fail_the_threshold(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    enroll(conn, "BN002", [unit(2)])
    calibrated = dict(cfg)
    calibrated["match"] = dict(cfg["match"], threshold=0.1, margin_top1_top2=0.0)
    probes = [emb(noisy(unit(1), 0.1, 0), 0), emb(noisy(unit(1), 0.1, 1), 1),
              emb(unit(2), 2), emb(unit(2), 3), emb(unit(2), 4)]
    result = matcher.match(probes, loaded_gallery(conn), calibrated)
    assert result.votes == 3 and result.passed_threshold is True
    # with only 2 votes for the winner the rule must fail
    two_votes = [probes[0], probes[1], probes[2]]
    assert matcher.match(two_votes, loaded_gallery(conn), calibrated).votes == 2
    assert matcher.match(two_votes, loaded_gallery(conn), calibrated).passed_threshold is False


def test_gallery_reloads_only_when_the_version_changes(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    gallery = loaded_gallery(conn)
    version = gallery.version
    assert gallery.refresh_if_changed(conn, T0) is False
    enroll(conn, "BN002", [unit(2)])
    assert gallery.refresh_if_changed(conn, T0) is True
    assert gallery.version > version and gallery.n_patients == 2


def test_best_match_for_enrollment_duplicate_check(conn, cfg):
    enroll(conn, "BN001", [unit(1)])
    enroll(conn, "BN002", [unit(2)])
    gallery = loaded_gallery(conn)
    code, score = matcher.best_match_for([noisy(unit(2), 0.05, 7)], gallery, cfg)
    assert code == "BN002" and score > 0.9
    # re-enrolling the same person must not flag themselves
    other, _ = matcher.best_match_for([noisy(unit(2), 0.05, 7)], gallery, cfg,
                                      exclude_code="BN002")
    assert other == "BN001"
