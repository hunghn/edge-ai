import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.pipeline import best_frame as bf
from edgeface.types import Embedding

T0 = 1000.0


@pytest.fixture
def cfg(repo_root):
    import os
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


def with_continuity(cfg, **overrides):
    merged = dict(cfg)
    best = dict(cfg["best_frame"])
    best["continuity"] = dict(cfg["best_frame"]["continuity"], **overrides)
    merged["best_frame"] = best
    return merged


def emb(seed):
    rng = np.random.RandomState(seed)
    vector = rng.randn(512).astype(np.float32)
    vector /= np.linalg.norm(vector)
    return Embedding(frame_id=seed, ts=float(seed), vector=vector, quality=None, raw_norm=20.0)


BOX = [100.0, 100.0, 300.0, 340.0]


def test_ready_as_soon_as_k_max_frames_are_collected(cfg):
    collector = bf.BestFrameCollector(cfg)
    for i in range(5):
        collector.add(emb(i), 0.5 + i * 0.1, BOX, T0 + i * 0.1)
    assert collector.poll(T0 + 0.5) == bf.READY
    status, embeddings, n_good = collector.result(T0 + 0.5)
    assert status == bf.READY and len(embeddings) == 5 and n_good == 5


def test_low_quality_when_the_window_closes_short(cfg):
    collector = bf.BestFrameCollector(cfg)
    collector.add(emb(1), 0.9, BOX, T0)
    collector.add(emb(2), 0.9, BOX, T0 + 0.2)
    assert collector.poll(T0 + 1.0) == bf.COLLECTING
    assert collector.poll(T0 + 1.6) == bf.LOW_QUALITY
    status, embeddings, n_good = collector.result(T0 + 1.6)
    assert (status, embeddings, n_good) == (bf.LOW_QUALITY, [], 2)


def test_min_good_frames_inside_the_window_are_enough(cfg):
    collector = bf.BestFrameCollector(cfg)
    for i in range(3):
        collector.add(emb(i), 0.5, BOX, T0 + i * 0.3)
    assert collector.poll(T0 + 1.6) == bf.READY


def test_keeps_the_best_k_by_quality(cfg):
    collector = bf.BestFrameCollector(cfg)
    qualities = [0.1, 0.9, 0.3, 0.8, 0.2, 0.95, 0.15]
    for i, q in enumerate(qualities):
        collector.add(emb(i), q, BOX, T0 + i * 0.05)
    kept = collector.qualities()
    assert len(kept) == 5
    assert kept == sorted(qualities, reverse=True)[:5]
    assert collector.n_good == len(qualities)            # every good frame is still counted


def test_fifo_order_when_quality_is_null(cfg):
    """With best_frame.quality_score unset (D-08), keep the first K frames, not the last."""
    collector = bf.BestFrameCollector(cfg)
    for i in range(7):
        collector.add(emb(i), None, BOX, T0 + i * 0.05)
    assert [e.frame_id for e in collector.embeddings()] == [0, 1, 2, 3, 4]


def test_resets_when_the_box_jumps_to_another_person(cfg):
    collector = bf.BestFrameCollector(with_continuity(cfg, iou_min=0.3))
    collector.add(emb(1), 0.8, BOX, T0)
    collector.add(emb(2), 0.8, BOX, T0 + 0.1)
    reason = collector.add(emb(3), 0.8, [900.0, 100.0, 1100.0, 340.0], T0 + 0.2)
    assert reason == bf.RESET_SUBJECT_CHANGED
    assert collector.count == 1 and collector.n_good == 1


def test_resets_when_the_face_disappears_for_too_long(cfg):
    collector = bf.BestFrameCollector(with_continuity(cfg, max_gap_s=0.5))
    collector.add(emb(1), 0.8, BOX, T0)
    assert collector.observe_miss(T0 + 0.2) is None
    assert collector.observe_miss(T0 + 0.9) == bf.RESET_SUBJECT_LOST
    assert collector.count == 0 and collector.started_at is None


def test_resets_when_the_face_stops_matching_itself(cfg):
    collector = bf.BestFrameCollector(with_continuity(cfg, cos_min=0.5))
    first = emb(1)
    collector.add(first, 0.8, BOX, T0)
    collector.add(first, 0.8, BOX, T0 + 0.1)
    assert collector.add(emb(99), 0.8, BOX, T0 + 0.2) == bf.RESET_SUBJECT_CHANGED


def test_quality_formulas(cfg):
    metrics = {"det_score": 0.9, "yaw": 0.0, "pitch": 0.0, "blur": 1000.0,
               "lum": 120.0, "raw_norm": 21.5}
    assert bf.quality_score(metrics, cfg) is None                 # null -> FIFO

    def with_formula(name):
        merged = dict(cfg)
        merged["best_frame"] = dict(cfg["best_frame"], quality_score=name)
        return merged

    perfect = bf.quality_score(metrics, with_formula("A"))
    tilted = bf.quality_score(dict(metrics, yaw=12.0), with_formula("A"))
    blurry = bf.quality_score(dict(metrics, blur=30.0), with_formula("A"))
    assert perfect == pytest.approx(0.9) and tilted < perfect and blurry < perfect
    assert 0.0 <= bf.quality_score(metrics, with_formula("B")) <= 1.0
    assert bf.quality_score(metrics, with_formula("C")) == 21.5
    with pytest.raises(ValueError):
        bf.quality_score(metrics, with_formula("Z"))
