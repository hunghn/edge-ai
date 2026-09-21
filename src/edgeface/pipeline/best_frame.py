"""S8: keep the best K embeddings of ONE person inside a short window.

Two things matter here. First, quality: only the best frames should reach the matcher.
Second, identity continuity: the buffer must never mix two people, or S9 would match a
blend of them. The collector therefore resets when the tracked box jumps or the face
disappears for too long.
"""
import heapq

import numpy as np

from edgeface.common.geometry import iou
from edgeface.common.log import get_logger

LOG = get_logger("best_frame")

COLLECTING = "COLLECTING"
READY = "READY"
LOW_QUALITY = "LOW_QUALITY"

RESET_SUBJECT_CHANGED = "SUBJECT_CHANGED"
RESET_SUBJECT_LOST = "SUBJECT_LOST"
RESET_CONSUMED = "CONSUMED"

_warned = set()


def _warn_once(key, message):
    if key not in _warned:
        _warned.add(key)
        LOG.warning(message)


def quality_score(obs_metrics, cfg):
    """Score a frame, or None while best_frame.quality_score is unset (D-08).

    obs_metrics: {"det_score", "yaw", "pitch", "blur", "lum", "raw_norm"}.
    Three candidate formulas are implemented so M9 can compare them (ablation A4):
      A  det_score x pose falloff x blur falloff
      B  weighted sum of the normalized signals
      C  the ArcFace feature norm, which correlates with quality on its own
    """
    best_cfg = cfg["best_frame"]
    formula = best_cfg.get("quality_score")
    if not formula:
        _warn_once("quality", "best_frame.quality_score is null (D-08): keeping frames FIFO")
        return None
    params = best_cfg.get("quality_params") or {}
    blur_ref = float(params.get("blur_ref", cfg["iqa"]["blur_min"] * 4))
    yaw_max = float(cfg["pose_fine"]["yaw_max_deg"])
    pitch_max = float(cfg["pose_fine"]["pitch_max_deg"])

    det_score = float(obs_metrics.get("det_score") or 0.0)
    yaw = abs(float(obs_metrics.get("yaw") or 0.0))
    pitch = abs(float(obs_metrics.get("pitch") or 0.0))
    blur = float(obs_metrics.get("blur") or 0.0)

    if formula == "A":
        return (det_score * max(0.0, 1.0 - yaw / yaw_max) * max(0.0, 1.0 - pitch / pitch_max)
                * min(1.0, blur / blur_ref))
    if formula == "B":
        weights = params.get("weights") or {"det": 0.25, "pose": 0.35, "blur": 0.4}
        pose_term = (max(0.0, 1.0 - yaw / yaw_max) + max(0.0, 1.0 - pitch / pitch_max)) / 2.0
        return (weights["det"] * det_score + weights["pose"] * pose_term
                + weights["blur"] * min(1.0, blur / blur_ref))
    if formula == "C":
        return float(obs_metrics.get("raw_norm") or 0.0)
    raise ValueError("unknown best_frame.quality_score: {}".format(formula))


class BestFrameCollector(object):
    """Collect up to k_max embeddings within window_s; below min_good it is low quality."""

    def __init__(self, cfg):
        best_cfg = cfg["best_frame"]
        self.k_max = int(best_cfg["k_max"])
        self.window_s = float(best_cfg["window_s"])
        self.min_good = int(best_cfg["min_good"])
        continuity = best_cfg.get("continuity") or {}
        self.iou_min = continuity.get("iou_min")
        self.max_gap_s = continuity.get("max_gap_s")
        self.cos_min = continuity.get("cos_min")
        self.reset(RESET_CONSUMED)

    def reset(self, reason=RESET_CONSUMED):
        self.started_at = None
        self.last_seen_at = None
        self.last_bbox = None
        self.n_good = 0
        self._heap = []          # (quality, counter, embedding); min-heap on quality
        self._counter = 0
        self.last_reset_reason = reason

    @property
    def count(self):
        return len(self._heap)

    def embeddings(self):
        """Kept embeddings, best quality first."""
        return [item[2] for item in sorted(self._heap, key=lambda item: -item[0])]

    def qualities(self):
        return [item[0] for item in sorted(self._heap, key=lambda item: -item[0])]

    def _continuity_broken(self, bbox, ts, vector):
        if self.last_bbox is not None and self.iou_min is not None:
            if iou(bbox, self.last_bbox) < self.iou_min:
                return RESET_SUBJECT_CHANGED
        if self.last_seen_at is not None and self.max_gap_s is not None:
            if ts - self.last_seen_at > self.max_gap_s:
                return RESET_SUBJECT_LOST
        if self.cos_min is not None and self._heap and vector is not None:
            mean = np.mean([item[2].vector for item in self._heap], axis=0)
            norm = np.linalg.norm(mean)
            if norm > 1e-6 and float(np.dot(vector, mean / norm)) < self.cos_min:
                return RESET_SUBJECT_CHANGED
        return None

    def add(self, embedding, quality, bbox, ts):
        """Add one good frame. Returns the reset reason when continuity broke first."""
        broken = self._continuity_broken(bbox, ts, embedding.vector)
        if broken:
            self.reset(broken)
        if self.started_at is None:
            self.started_at = ts
        self.last_seen_at = ts
        self.last_bbox = bbox
        self.n_good += 1
        # FIFO order when quality_score is still null (D-08): the counter breaks ties.
        score = self._counter * -1.0 if quality is None else float(quality)
        self._counter += 1
        entry = (score, self._counter, embedding._replace(quality=quality))
        if len(self._heap) < self.k_max:
            heapq.heappush(self._heap, entry)
        else:
            heapq.heappushpop(self._heap, entry)
        return broken

    def observe_miss(self, ts, reason=None):
        """A frame that failed a gate: it does not count, but the gap may reset us."""
        if (self.started_at is not None and self.last_seen_at is not None
                and self.max_gap_s is not None and ts - self.last_seen_at > self.max_gap_s):
            self.reset(RESET_SUBJECT_LOST)
            return RESET_SUBJECT_LOST
        return None

    def poll(self, ts):
        """COLLECTING | READY | LOW_QUALITY."""
        if self.started_at is None:
            return COLLECTING
        if self.count >= self.k_max:
            return READY
        if ts - self.started_at >= self.window_s:
            return READY if self.n_good >= self.min_good else LOW_QUALITY
        return COLLECTING

    def result(self, ts):
        """(status, embeddings, n_good). Does not reset: the caller decides."""
        status = self.poll(ts)
        if status == READY:
            return status, self.embeddings(), self.n_good
        return status, [], self.n_good
