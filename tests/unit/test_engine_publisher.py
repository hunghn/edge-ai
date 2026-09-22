"""Publisher: debounced state writes, atomic preview file, command intake."""
import os

import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.engine.publisher import Publisher
from edgeface.storage import db, kiosk_ipc

T0 = 1000.0


@pytest.fixture
def cfg(repo_root, tmp_path):
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    merged = dict(base)
    merged["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "preview.jpg"),
                           preview_fps=1000)
    return merged


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def test_repeated_state_is_not_rewritten(conn, cfg):
    pub = Publisher(conn, cfg)
    assert pub.publish("GUIDING", "STEP_CLOSER", now=T0) == 1
    assert pub.publish("GUIDING", "STEP_CLOSER", now=T0 + 0.1) is None   # unchanged
    assert pub.publish("GUIDING", "LOOK_STRAIGHT", now=T0 + 0.2) == 2    # changed
    # ... but an unchanged state is refreshed periodically so the kiosk can detect a stall
    assert pub.publish("GUIDING", "LOOK_STRAIGHT", now=T0 + 1.0) == 3


def test_force_always_writes(conn, cfg):
    pub = Publisher(conn, cfg)
    pub.publish("IDLE", now=T0)
    assert pub.publish("IDLE", now=T0 + 0.01, force=True) == 2


def test_payload_round_trips(conn, cfg):
    pub = Publisher(conn, cfg)
    pub.publish("AWAIT_NURSE", session_id="s1",
                payload={"candidate": {"code": "BN001"}, "decision": "review_required"},
                now=T0)
    state = kiosk_ipc.read_state(conn, after_seq=0)
    assert state["state"] == "AWAIT_NURSE" and state["session_id"] == "s1"
    assert state["payload"]["candidate"]["code"] == "BN001"


def test_preview_is_written_atomically(conn, cfg):
    import cv2

    pub = Publisher(conn, cfg)
    image = np.full((720, 1280, 3), 128, dtype=np.uint8)
    assert pub.write_preview(image, now=T0) is True
    path = cfg["kiosk"]["preview_path"]
    assert os.path.isfile(path) and not os.path.exists(path + ".tmp")
    decoded = cv2.imread(path)
    assert decoded is not None and decoded.shape[1] == cfg["kiosk"]["preview_width"]


def test_preview_respects_its_frame_rate(conn, repo_root, tmp_path):
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    slow = dict(base)
    slow["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "p.jpg"), preview_fps=5)
    pub = Publisher(conn, slow)
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    assert pub.write_preview(image, now=T0) is True
    assert pub.write_preview(image, now=T0 + 0.1) is False     # 5 fps -> 0.2 s apart
    assert pub.write_preview(image, now=T0 + 0.3) is True


def test_claim_commands_passes_through(conn, cfg):
    pub = Publisher(conn, cfg)
    with db.transaction(conn):
        kiosk_ipc.send_command(conn, "confirm", {"code": "BN001"}, at=T0)
    commands = pub.claim_commands(now=T0 + 1)
    assert [c["type"] for c in commands] == ["confirm"]
    assert pub.claim_commands(now=T0 + 2) == []
