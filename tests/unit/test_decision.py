import os

import pytest

from edgeface import config as cfg_mod
from edgeface.pipeline import best_frame as bf
from edgeface.pipeline.decision import SessionEvidence, decide
from edgeface.pipeline.matcher import MatchResult
from edgeface.types import Decision


@pytest.fixture
def cfg(repo_root):
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


@pytest.fixture
def calibrated(cfg):
    """A config as it will look once M9 closes D-01/D-02.

    enabled_outcomes stays at the three values the spec names: until D-04 adds the
    others to the Decision enum, config.validate() refuses to enable them.
    """
    merged = dict(cfg)
    merged["match"] = dict(cfg["match"], threshold=0.45, margin_top1_top2=0.05)
    merged["decision"] = dict(cfg["decision"], no_match_below=0.25)
    return merged


def result(top1="BN001", score=0.7, margin=0.2, votes=5, passed=True):
    return MatchResult(top1, score, "BN002", None if margin is None else score - margin,
                       margin, votes, 5, [], passed)


def ready(match=None, spoof=0, n_good=5):
    return SessionEvidence(spoof_frames=spoof, min_p_real=0.9, collector=bf.READY,
                           n_good_frames=n_good, match=match)


def test_r1_spoof_wins_over_everything(calibrated):
    evidence = SessionEvidence(spoof_frames=2, min_p_real=0.1, collector=bf.LOW_QUALITY,
                               n_good_frames=1, match=result())
    out = decide(evidence, calibrated)
    assert out.decision is Decision.SPOOF_SUSPECT and out.rule_id == "R1"
    assert out.candidate is None                      # never show a name on a spoof alert


def test_r1_needs_the_configured_number_of_frames(calibrated):
    """C-20: one rejected frame is not an alarm, two are."""
    assert calibrated["decision"]["spoof_min_frames"] == 2
    one = decide(ready(result(), spoof=1), calibrated)
    assert one.decision is not Decision.SPOOF_SUSPECT
    two = decide(ready(result(), spoof=2), calibrated)
    assert two.decision is Decision.SPOOF_SUSPECT


def test_r2_low_quality(calibrated):
    evidence = SessionEvidence(spoof_frames=0, collector=bf.LOW_QUALITY, n_good_frames=2,
                               match=None)
    out = decide(evidence, calibrated)
    assert out.decision is Decision.LOW_QUALITY and out.rule_id == "R2"


def test_r3_uncalibrated_thresholds_go_to_review(cfg):
    out = decide(ready(result(passed=None)), cfg)
    assert out.decision is Decision.REVIEW_REQUIRED and out.rule_id == "R3"
    assert out.candidate["code"] == "BN001"           # the nurse still sees the best guess


def test_r4_no_match(calibrated):
    """R4 fires, but 'no_match' is not enabled yet (D-04), so the nurse sees a review."""
    out = decide(ready(result(score=0.2, passed=False)), calibrated)
    assert out.rule_id == "R4" and out.decision is Decision.REVIEW_REQUIRED


def test_r5_confident_candidate(calibrated):
    out = decide(ready(result(passed=True)), calibrated)
    assert out.rule_id == "R5" and out.decision is Decision.REVIEW_REQUIRED
    assert out.candidate["votes"] == 5           # the candidate is shown either way


def test_r6_below_threshold(calibrated):
    out = decide(ready(result(score=0.4, passed=False)), calibrated)
    assert out.rule_id == "R6" and out.decision is Decision.REVIEW_REQUIRED


def test_config_refuses_outcomes_the_code_cannot_express(tmp_path, repo_root):
    """Enabling a D-04 outcome before the enum knows it must fail loudly, not silently."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("decision:\n  enabled_outcomes: [review_required, candidate_suggested]\n")
    with pytest.raises(ValueError) as excinfo:
        cfg_mod.load_config(str(bad), default_path=os.path.join(
            repo_root, "configs", "default.yaml"))
    assert "candidate_suggested" in str(excinfo.value)


def test_every_decision_requires_the_nurse(calibrated, cfg):
    cases = [
        decide(ready(result(), spoof=3), calibrated),
        decide(SessionEvidence(collector=bf.LOW_QUALITY, n_good_frames=0), calibrated),
        decide(ready(result(passed=True)), calibrated),
        decide(ready(result(score=0.1, passed=False)), calibrated),
        decide(ready(result(passed=None)), cfg),
    ]
    assert all(case.requires_nurse for case in cases)


def test_missing_match_is_handled(calibrated):
    out = decide(ready(match=None), calibrated)
    assert out.rule_id == "R3" and out.candidate is None
