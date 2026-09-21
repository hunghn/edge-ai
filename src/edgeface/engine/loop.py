"""Per-frame orchestration of S1-S8.

This module holds no thresholds and no maths: it calls the stages in order, stops at the
first failed gate and reports what the kiosk should say. Every threshold lives in the
config, every computation lives in its stage.

Order matters for cost as much as for correctness. S3 is geometry over five keypoints
and costs nothing, so it runs before the two anti-spoofing inferences; S5-S7 only run on
frames that already passed the spoof check. Measured on the Nano (M2), a frame that
reaches S7 costs about 78 ms, while one rejected at S3 costs about 41 ms.
"""
from collections import namedtuple

from edgeface.common.timing import timed, timer
from edgeface.pipeline import align as align_stage
from edgeface.pipeline import antispoof, best_frame, detect, embed, pose, quality, subject
from edgeface.types import FaceObs, GuidanceCode

# guidance : GuidanceCode or None when the frame went all the way through
# stage    : the stage that stopped the frame ("S1".."S8"), or None
# obs      : FaceObs with everything computed so far
# collector: COLLECTING | READY | LOW_QUALITY
FrameOutcome = namedtuple("FrameOutcome", ["guidance", "stage", "obs", "collector", "reset"])


@timed("e2e")
def process_frame(frame, models, cfg, collector):
    """Run one frame through S1-S8 and fold it into the collector."""
    obs = FaceObs(frame_id=frame.frame_id, ts=frame.ts, det=None)

    result = detect.detect(frame.image, models["detector"], cfg)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S1", obs, collector.poll(frame.ts), reset)

    result = subject.choose_subject(result.data, frame.image.shape, cfg)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S2", obs._replace(det=result.data),
                            collector.poll(frame.ts), reset)
    detection = result.data
    obs = obs._replace(det=detection)

    result = pose.coarse_pose(detection, cfg)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S3", obs._replace(pose_coarse=result.data),
                            collector.poll(frame.ts), reset)
    obs = obs._replace(pose_coarse=result.data)

    result = antispoof.check_real(frame.image, detection, models, cfg)
    obs = obs._replace(spoof=result.data)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S4", obs, collector.poll(frame.ts), reset)

    with timer("S5_landmark"):
        landmarks = models["landmark"].predict(frame.image, detection.bbox)
    obs = obs._replace(lmk106=landmarks)
    result = pose.fine_pose(landmarks, frame.image.shape, cfg)
    obs = obs._replace(pose_fine=result.data)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S5", obs, collector.poll(frame.ts), reset)

    result = quality.image_quality(frame.image, detection.bbox, cfg)
    obs = obs._replace(iqa=result.data)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S5", obs, collector.poll(frame.ts), reset)

    result = align_stage.align(frame.image, detection, landmarks, cfg)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S6", obs, collector.poll(frame.ts), reset)
    obs = obs._replace(aligned=result.data)

    result = embed.embed(result.data, models["recognizer"], frame.frame_id, frame.ts)
    if not result.ok:
        reset = collector.observe_miss(frame.ts, result.reason)
        return FrameOutcome(result.reason, "S7", obs, collector.poll(frame.ts), reset)
    embedding = result.data
    obs = obs._replace(embedding=embedding)

    score = best_frame.quality_score({
        "det_score": detection.score,
        "yaw": obs.pose_fine["yaw"], "pitch": obs.pose_fine["pitch"],
        "blur": obs.iqa["blur"], "lum": obs.iqa["lum"], "raw_norm": embedding.raw_norm,
    }, cfg)
    reset = collector.add(embedding, score, detection.bbox, frame.ts)
    obs = obs._replace(quality=score)
    return FrameOutcome(None, None, obs, collector.poll(frame.ts), reset)


def guidance_of(outcome):
    """What the kiosk should display for this frame."""
    return outcome.guidance or GuidanceCode.HOLD_STILL


def new_collector(cfg):
    return best_frame.BestFrameCollector(cfg)
