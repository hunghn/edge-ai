"""S10: the rule engine.

Ordered rules over the evidence from S4, S8 and S9. The order is fixed in code, every
number comes from the config, and each rule has an id that is written to the session row
so M9 can count how often each fired.

The spec names three outcomes (spoof_suspect, low_quality, review_required) and defers
the rest to §6.3. candidate_suggested was enabled on 2026-10-08 (D-04); an outcome the
config does not enable, such as "not in today's list", becomes review_required, which is
the safe direction — the nurse looks at it either way.

Whatever the outcome, requires_nurse is always True: the kiosk never admits anyone.
"""
from collections import namedtuple

from edgeface.common.log import get_logger
from edgeface.common.timing import timed
from edgeface.pipeline import best_frame as bf
from edgeface.types import Decision

LOG = get_logger("decision")

# spoof_frames  : frames rejected by S4 during the collection window
# collector     : READY | LOW_QUALITY
# match         : MatchResult or None
SessionEvidence = namedtuple("SessionEvidence", [
    "spoof_frames", "min_p_real", "collector", "n_good_frames", "match",
])
SessionEvidence.__new__.__defaults__ = (0, None, bf.COLLECTING, 0, None)

DecisionResult = namedtuple("DecisionResult", [
    "decision", "rule_id", "candidate", "requires_nurse", "note",
])

CANDIDATE_SUGGESTED = Decision.CANDIDATE_SUGGESTED.value   # D-04, enabled 2026-10-08
NO_MATCH = "no_match"                         # proposed in D-04, not enabled yet

_warned = set()


def _warn_once(key, message):
    if key not in _warned:
        _warned.add(key)
        LOG.warning(message)


def _candidate(match):
    if match is None or match.top1_code is None:
        return None
    # top2 rides along so the kiosk can show the nurse who else came close. Two patients
    # who look alike is the failure this clinic actually has to catch, and it is
    # invisible if only the winner ever reaches the screen.
    return {"code": match.top1_code, "score": match.top1_score, "margin": match.margin,
            "votes": match.votes, "k": match.k,
            "top2_code": match.top2_code, "top2_score": match.top2_score}


def _resolve(value, cfg, rule_id, match, note=None):
    """Emit `value` if the config enables it, otherwise fall back to review_required.

    config.validate() guarantees every enabled outcome exists in the Decision enum, so
    the only way here is a rule proposing an outcome that D-04 has not enabled yet.
    """
    enabled = cfg["decision"].get("enabled_outcomes") or ()
    if value in enabled:
        decision = Decision(value)
    else:
        _warn_once(value, "decision outcome '{}' is not enabled (D-04): "
                          "reporting review_required instead".format(value))
        decision = Decision.REVIEW_REQUIRED
    return DecisionResult(decision, rule_id, _candidate(match), True, note)


@timed("S10")
def decide(evidence, cfg):
    """First matching rule wins."""
    decision_cfg = cfg["decision"]
    match = evidence.match

    # R1 — spoofing beats everything, including a bad-quality session.
    spoof_min = decision_cfg.get("spoof_min_frames")
    if spoof_min is not None and evidence.spoof_frames >= spoof_min:
        return _resolve(Decision.SPOOF_SUSPECT.value, cfg, "R1", None,
                        note="{} frames rejected by S4".format(evidence.spoof_frames))

    # R2 — not enough usable frames to compare anything.
    if evidence.collector == bf.LOW_QUALITY:
        return _resolve(Decision.LOW_QUALITY.value, cfg, "R2", None,
                        note="{} good frames".format(evidence.n_good_frames))

    # R3 — thresholds not calibrated yet: show the best guess, let the nurse judge.
    if match is None or match.passed_threshold is None:
        if cfg["match"].get("threshold") is None:
            _warn_once("thresholds", "match.threshold is null (D-01): "
                                     "every session goes to review_required")
        return _resolve(Decision.REVIEW_REQUIRED.value, cfg, "R3", match,
                        note="thresholds not calibrated")

    # R4 — nobody in today's gallery is even close.
    no_match_below = decision_cfg.get("no_match_below")
    if match.top1_code is None or (no_match_below is not None
                                   and match.top1_score < no_match_below):
        return _resolve(NO_MATCH, cfg, "R4", match, note="top1 below no_match_below")

    # R5 — a confident match. The nurse still has to confirm it.
    if match.passed_threshold:
        return _resolve(CANDIDATE_SUGGESTED, cfg, "R5", match, note="passed S9 thresholds")

    # R6 — everything else.
    return _resolve(Decision.REVIEW_REQUIRED.value, cfg, "R6", match,
                    note="below threshold or too few votes")
