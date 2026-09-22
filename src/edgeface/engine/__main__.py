"""The engine process: camera -> S1..S10 -> session -> SQLite.

    python3 -m edgeface.engine --config configs/nano.yaml

The loop is deliberately single-threaded apart from capture: there is one GPU, so
running stages concurrently would only add contention. Each iteration takes the newest
frame, runs the pipeline, feeds the session machine and executes whatever actions it
returns.

Offline use (dev machine, recorded video, nobody at the kiosk):

    python3 -m edgeface.engine --config configs/dev.yaml --auto-nurse confirm --max-frames 300
"""
import argparse
import os
import signal
import sys

from edgeface import config as cfg_mod
from edgeface.common.log import get_logger
from edgeface.common.timing import RECORDER
from edgeface.engine import enroll as enroll_mod
from edgeface.engine import loop as engine_loop
from edgeface.engine import session as session_mod
from edgeface.engine.models import close_models, load_models
from edgeface.engine.publisher import Publisher
from edgeface.engine.session import Session
from edgeface.gallery import retention
from edgeface.gallery.gallery import Gallery
from edgeface.pipeline import best_frame as bf
from edgeface.pipeline import matcher
from edgeface.pipeline.capture import CaptureThread, lockstep_from_config, source_from_config
from edgeface.pipeline.decision import SessionEvidence, decide
from edgeface.storage import clock, db, evidence, metrics, outbox, sessions

LOG = get_logger("engine")
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _abs_path(path):
    return path if os.path.isabs(path) else os.path.join(REPO, path)


class Engine(object):
    def __init__(self, cfg, auto_nurse=None):
        self.cfg = cfg
        self.auto_nurse = auto_nurse
        self.conn = db.open_db(_abs_path(cfg["storage"]["db_path"]))
        self.models = load_models(cfg, strict=False)
        self.gallery = Gallery(self.models["recognizer_sha256"]).load(self.conn, clock.now())
        self.publisher = Publisher(self.conn, cfg)
        self.collector = engine_loop.new_collector(cfg)
        self.session = Session(cfg)
        self.capture = CaptureThread(
            source_from_config(cfg), read_fail_max=cfg["capture"].get("read_fail_max", 30),
            reconnect_s=cfg["capture"].get("reconnect_s", 2.0),
            lockstep=lockstep_from_config(cfg))
        self.evidence_dir = _abs_path(cfg["storage"].get("evidence_dir", "var/evidence"))
        self.last_frame = None
        self.worst_spoof_frame = None
        self.running = False

        closed = sessions.close_dangling(self.conn)   # sessions left open by a crash
        if closed:
            LOG.warning("closed %d session(s) left open by a previous run", closed)

    # ------------------------------------------------------------------ actions
    def _open_session(self, payload, now):
        with db.transaction(self.conn):
            self.session.session_id = sessions.open_session(
                self.conn, payload["kind"], now,
                ttl_days=self.cfg["retention"]["sessions_days"])
        self.session.kind = payload["kind"]
        LOG.info("session %s opened (%s)", self.session.session_id[:8], payload["kind"])

    def _close_session(self, payload, now):
        session_id = self.session.session_id
        if session_id is None:
            return
        decision = self.session.decision
        fields = {
            "nurse_action": payload.get("nurse_action"),
            "confirmed_code": payload.get("confirmed_code"),
            "operator_id": payload.get("operator_id"),
            "n_good_frames": self.session.n_good_frames,
            "spoof_frames": self.session.spoof_frames,
            "min_p_real": self.session.min_p_real,
        }
        if decision is not None:
            fields["decision"] = decision.decision.value
            fields["rule_id"] = decision.rule_id
            candidate = decision.candidate
            if candidate:
                fields.update({"top1_code": candidate["code"], "top1_score": candidate["score"],
                               "votes": candidate["votes"]})
        # One row per stage for THIS session, then start fresh. The median is stored
        # rather than the mean: the first frame after start-up carries the TensorRT
        # warm-up (measured at ~1.3 s) and would drag a mean far off.
        latency_rows = [(stage, stats["p50"]) for stage, stats in RECORDER.summary().items()]
        with db.transaction(self.conn):
            sessions.close_session(self.conn, session_id, ended_at=now, **fields)
            outbox.enqueue(self.conn, "session.closed", dict(
                fields, session_id=session_id, kind=self.session.kind, started_at=now), at=now)
            if latency_rows:
                metrics.add_latency_batch(self.conn, latency_rows, session_id=session_id,
                                          ts=now)
        RECORDER.reset()
        LOG.info("session %s closed: %s / %s", session_id[:8],
                 fields.get("decision"), fields.get("nurse_action"))
        self.session.decision = None
        self.session.session_id = None

    def _run_decision(self, payload, now):
        status = payload["collector"]
        embeddings = self.collector.embeddings() if status == bf.READY else []
        match = matcher.match(embeddings, self.gallery, self.cfg) if embeddings else None
        result = decide(SessionEvidence(
            spoof_frames=self.session.spoof_frames, min_p_real=self.session.min_p_real,
            collector=status, n_good_frames=self.collector.n_good, match=match), self.cfg)
        self.session.n_good_frames = self.collector.n_good
        self._execute(self.session.on_decision(result, now), now)

    def _save_evidence(self, payload, now):
        """C-16: store only the face crop of the worst frame, with its own TTL."""
        import cv2

        from edgeface.common.geometry import xyxy_to_xywh
        from edgeface.models.minifasnet import crop_image

        frame, detection = self.worst_spoof_frame or (None, None)
        if frame is None:
            return
        spoof_cfg = self.cfg["antispoof"].get("evidence") or {}
        if spoof_cfg.get("save") == "none":
            return
        if spoof_cfg.get("save") == "frame":
            image = frame.image
        else:
            image = crop_image(frame.image, xyxy_to_xywh(detection.bbox),
                               spoof_cfg.get("crop_scale", 4.0), 320, 320)
        ok, buffer = cv2.imencode(".jpg", image,
                                  [int(cv2.IMWRITE_JPEG_QUALITY),
                                   int(spoof_cfg.get("jpeg_quality", 90))])
        if not ok:
            LOG.warning("could not encode spoof evidence")
            return
        with db.transaction(self.conn):
            row = evidence.save(self.conn, payload.get("session_id"), buffer.tobytes(),
                                self.evidence_dir, spoof_cfg.get("ttl_days", 7), now)
            outbox.enqueue(self.conn, "spoof.detected", {
                "session_id": payload.get("session_id"), "evidence_sha256": row["sha256"],
                "min_p_real": self.session.min_p_real,
                "spoof_frames": self.session.spoof_frames}, at=now)
        LOG.warning("spoof evidence saved for session %s", str(payload.get("session_id"))[:8])

    def _publish(self, payload, now):
        state = payload["state"]
        body = {k: v for k, v in payload.items() if k not in ("state", "guidance")}
        self.publisher.publish(state, payload.get("guidance"), self.session.session_id,
                               body or None, now)

    def _start_enroll(self, form, now):
        ok, reason = enroll_mod.validate_form(form, self.conn)
        if not ok:
            self.session.enroll_error = reason
            self.session._enter(session_mod.ENROLL_ERROR, now)
            self.publisher.publish(session_mod.ENROLL_ERROR, reason, None, {"reason": reason},
                                   now, force=True)
            return
        with db.transaction(self.conn):
            self.session.session_id = sessions.open_session(
                self.conn, sessions.KIND_ENROLL, now,
                ttl_days=self.cfg["retention"]["sessions_days"])
        self.session.kind = sessions.KIND_ENROLL
        LOG.info("enrollment started for %s", form.get("patient_code"))

    def _save_enroll(self, payload, now):
        embeddings = self.collector.embeddings()
        if payload["stage"] == "review":
            review = enroll_mod.review(self.session.enroll_form, embeddings,
                                       self.gallery, self.cfg)
            self.publisher.publish(session_mod.ENROLL_REVIEW, None, self.session.session_id, {
                "n_templates": review.n_templates, "warnings": review.warnings,
                "duplicate_code": review.duplicate_code,
                "duplicate_score": review.duplicate_score,
                "self_consistency": review.self_consistency, "blocked": review.blocked}, now,
                force=True)
            return
        form = payload.get("form") or self.session.enroll_form
        result = enroll_mod.commit(self.conn, form, embeddings, self.cfg,
                                   self.models["recognizer_sha256"],
                                   operator_id=(form or {}).get("operator_id"), now=now,
                                   session_id=self.session.session_id)
        self._close_session({"nurse_action": "confirm",
                             "confirmed_code": form["patient_code"]}, now)
        self.session.session_id = None
        self.gallery.refresh_if_changed(self.conn, now)
        LOG.info("enrollment committed: %s", result)

    def _cancel_enroll(self, payload, now):
        if self.session.session_id is not None:
            self._close_session({"nurse_action": "cancel"}, now)
            self.session.session_id = None

    def _execute(self, actions, now):
        handlers = {
            session_mod.OPEN_SESSION: self._open_session,
            session_mod.CLOSE_SESSION: self._close_session,
            session_mod.DECIDE: self._run_decision,
            session_mod.SAVE_EVIDENCE: self._save_evidence,
            session_mod.PUBLISH: self._publish,
            session_mod.START_ENROLL: self._start_enroll,
            session_mod.SAVE_ENROLL: self._save_enroll,
            session_mod.CANCEL_ENROLL: self._cancel_enroll,
            session_mod.RESET_COLLECTOR: lambda payload, when: self.collector.reset(
                payload.get("reason", bf.RESET_CONSUMED)),
        }
        for action in actions:
            handler = handlers.get(action.kind)
            if handler is None:
                LOG.error("unknown action %s", action.kind)
                continue
            handler(action.payload or {}, now)

    # ------------------------------------------------------------------ main loop
    def _auto_command(self):
        """Offline mode: answer for the nurse so a recorded run reaches a decision."""
        if self.auto_nurse and self.session.state == session_mod.AWAIT_NURSE:
            return [{"type": self.auto_nurse, "payload": {}}]
        return []

    def step(self, timeout=1.0):
        now = clock.now()
        frame = self.capture.ring.get_latest(
            after_id=self.last_frame.frame_id if self.last_frame else -1, timeout=timeout)
        if frame is None:
            if self.capture.error:
                self._execute(self.session.on_camera_error(now), now)
            self._execute(self.session.on_tick(clock.now()), clock.now())
            return False

        self._execute(self.session.on_camera_ok(now), now)
        self.last_frame = frame
        self.publisher.write_preview(frame.image, now)

        busy = self.session.state in (session_mod.AWAIT_NURSE, session_mod.COOLDOWN,
                                      session_mod.ENROLL_REVIEW, session_mod.ENROLL_ERROR)
        if not busy:
            outcome = engine_loop.process_frame(frame, self.models, self.cfg, self.collector)
            if outcome.guidance == "SPOOF_SUSPECT" and outcome.obs.det is not None:
                worst = self.worst_spoof_frame
                if worst is None or (outcome.obs.spoof is not None
                                     and outcome.obs.spoof.p_real < self.session.min_p_real):
                    self.worst_spoof_frame = (frame, outcome.obs.det)
            self._execute(self.session.on_frame(outcome, frame.ts), frame.ts)

        self.publisher.heartbeat(now)     # prove the engine is alive even while waiting

        for command in self.publisher.claim_commands(now) + self._auto_command():
            self._execute(self.session.on_command(command, clock.now()), clock.now())
        self._execute(self.session.on_tick(clock.now()), clock.now())

        if self.session.state == session_mod.IDLE:
            self.gallery.refresh_if_changed(self.conn, now)
            if retention.due(self.conn, now, self.cfg["retention"]["interval_s"]):
                retention.run_once(self.conn, self.cfg, now, self.evidence_dir)
        return True

    def run(self, max_frames=0):
        self.capture.start()
        self.running = True
        self.publisher.publish(session_mod.IDLE, None, None, None, force=True)
        frames = 0
        try:
            while self.running:
                if self.step():
                    frames += 1
                if max_frames and frames >= max_frames:
                    break
                if (getattr(self.capture.source, "eof", False)
                        and self.capture.ring.peek() is None
                        and not self.capture.is_running()):
                    LOG.info("video source ended")
                    break
        finally:
            self.shutdown()
        return frames

    def stop(self, *_args):
        LOG.info("stopping")
        self.running = False

    def shutdown(self):
        now = clock.now()
        if self.session.session_id is not None:
            self._close_session({"nurse_action": "cancel"}, now)
        self.capture.stop()
        close_models(self.models)
        summary = RECORDER.summary()
        if summary:
            LOG.info("latency p50: %s", {k: round(v["p50"], 1) for k, v in summary.items()})
        self.conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(REPO, "configs", "nano.yaml"))
    ap.add_argument("--auto-nurse", choices=("confirm", "reject", "retry"),
                    help="offline runs: answer on the nurse's behalf")
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args(argv)

    cfg = cfg_mod.load_config(args.config)
    engine = Engine(cfg, auto_nurse=args.auto_nurse)
    signal.signal(signal.SIGTERM, engine.stop)
    signal.signal(signal.SIGINT, engine.stop)
    frames = engine.run(max_frames=args.max_frames)
    LOG.info("processed %d frames", frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
