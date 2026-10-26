"""Publisher: debounced state writes, atomic preview file, command intake."""
import os

import numpy as np
import pytest

from edgeface import config as cfg_mod
from edgeface.common import preview_frame
from edgeface.engine.publisher import Publisher
from edgeface.storage import db, kiosk_ipc

T0 = 1000.0


@pytest.fixture
def cfg(repo_root, tmp_path):
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    merged = dict(base)
    merged["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "preview.rgb"),
                           preview_fps=1000)
    return merged


def with_kiosk(cfg, **overrides):
    merged = dict(cfg)
    merged["kiosk"] = dict(cfg["kiosk"], **overrides)
    return merged


def read_raw(path):
    """The raw preview file as a BGR array, so it compares with the camera frame."""
    import cv2

    with open(path, "rb") as f:
        data = f.read()
    width, height = preview_frame.decode_header(data)
    assert len(data) == preview_frame.expected_size(width, height)
    rgb = np.frombuffer(data[preview_frame.RAW_HEADER.size:], dtype=np.uint8)
    return cv2.cvtColor(rgb.reshape(height, width, 3), cv2.COLOR_RGB2BGR)


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
    pub = Publisher(conn, cfg)
    image = np.full((720, 1280, 3), 128, dtype=np.uint8)
    assert pub.write_preview(image, now=T0) is True
    path = cfg["kiosk"]["preview_path"]
    assert os.path.isfile(path) and not os.path.exists(path + ".tmp")
    assert read_raw(path).shape == (720, 1280, 3)


def test_the_raw_preview_keeps_the_camera_resolution_and_colours(conn, cfg):
    """C-09: every pixel of the 1080p frame, in RGB order behind the header."""
    assert cfg["kiosk"]["preview_format"] == "raw" and cfg["kiosk"]["preview_width"] is None
    pub = Publisher(conn, cfg)
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[:, :, 0] = 200                       # blue in OpenCV's BGR
    frame[10, 20] = (1, 2, 3)
    assert pub.write_preview(frame, now=T0) is True
    with open(cfg["kiosk"]["preview_path"], "rb") as f:
        data = f.read()
    assert preview_frame.decode_header(data) == (1920, 1080)
    assert len(data) == 8 + 1920 * 1080 * 3
    first = data[preview_frame.RAW_HEADER.size:preview_frame.RAW_HEADER.size + 3]
    assert tuple(bytearray(first)) == (0, 0, 200)                     # stored as RGB
    assert np.array_equal(read_raw(cfg["kiosk"]["preview_path"]), frame)


def test_a_preview_width_still_scales_the_picture(conn, cfg):
    pub = Publisher(conn, with_kiosk(cfg, preview_width=480))
    assert pub.write_preview(np.zeros((1080, 1920, 3), np.uint8), now=T0) is True
    assert read_raw(cfg["kiosk"]["preview_path"]).shape == (270, 480, 3)


def test_the_jpeg_format_is_still_available(conn, cfg, tmp_path):
    import cv2

    jpeg_cfg = with_kiosk(cfg, preview_format="jpeg", preview_width=960,
                          preview_path=str(tmp_path / "preview.jpg"))
    pub = Publisher(conn, jpeg_cfg)
    assert pub.write_preview(np.full((1080, 1920, 3), 90, np.uint8), now=T0) is True
    decoded = cv2.imread(jpeg_cfg["kiosk"]["preview_path"])
    assert decoded is not None and decoded.shape == (540, 960, 3)


def test_drawing_the_box_never_touches_the_camera_frame(conn, cfg):
    """The ring buffer's frame is still in use by the pipeline when the preview runs."""
    for kiosk in ({}, {"preview_format": "jpeg"}):
        pub = Publisher(conn, with_kiosk(cfg, **kiosk))
        frame = np.full((1080, 1920, 3), 128, np.uint8)
        before = frame.copy()
        pub.store_preview(frame, (0.25, 0.25, 0.75, 0.75), True)
        assert np.array_equal(frame, before)


def test_the_preview_thread_takes_the_frame_off_the_loop(conn, cfg):
    """submit() is a hand-over: the 22 ms write happens on the preview thread."""
    import time

    pub = Publisher(conn, cfg)
    writer = pub.start_preview_thread()
    try:
        frame = np.full((1080, 1920, 3), 77, np.uint8)
        started = time.time()
        assert pub.write_preview(frame, now=T0) is True
        assert (time.time() - started) < 0.005
        deadline = time.time() + 5.0
        while writer.written < 1 and time.time() < deadline:
            time.sleep(0.01)
        assert writer.written >= 1
        assert read_raw(cfg["kiosk"]["preview_path"])[0, 0, 0] == 77
    finally:
        pub.stop_preview_thread()
    assert not writer.is_running()


def test_the_preview_thread_keeps_only_the_newest_frame(conn, cfg):
    from edgeface.engine.publisher import PreviewWriter

    stored = []

    class Recorder(object):
        def store_preview(self, image, box, good):
            stored.append(int(image[0, 0, 0]))

    writer = PreviewWriter(Recorder(), period=0.2)
    writer.submit(np.full((4, 4, 3), 1, np.uint8))
    writer.submit(np.full((4, 4, 3), 2, np.uint8))     # replaces 1 before the thread runs
    writer.start()
    try:
        import time

        deadline = time.time() + 2.0
        while not stored and time.time() < deadline:
            time.sleep(0.01)
    finally:
        writer.stop()
    assert stored == [2]


def test_preview_respects_its_frame_rate(conn, repo_root, tmp_path):
    base = cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    slow = dict(base)
    slow["kiosk"] = dict(base["kiosk"], preview_path=str(tmp_path / "p.rgb"), preview_fps=5)
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


def _preview(pub, cfg, image, box=None, good=False, at=T0):
    assert pub.write_preview(image, box, at, good) is True
    return read_raw(cfg["kiosk"]["preview_path"])


def test_the_face_outline_lands_where_the_face_is(conn, cfg):
    """The box is given as fractions of the frame and drawn on the preview picture,
    so the only thing that can go wrong is the scaling - which is what this checks."""
    pub = Publisher(conn, cfg)
    grey = np.full((720, 1280, 3), 128, dtype=np.uint8)

    plain = _preview(pub, cfg, grey, None, at=T0)
    drawn = _preview(pub, cfg, grey, (0.25, 0.25, 0.75, 0.75), True, at=T0 + 10)

    height, width = drawn.shape[:2]
    # The outline is on the rectangle's edge...
    assert not np.array_equal(drawn[int(0.25 * height), int(0.5 * width)],
                              plain[int(0.25 * height), int(0.5 * width)])
    # ...and nowhere near the corner of the frame.
    assert np.array_equal(drawn[2, 2], plain[2, 2])


def test_a_good_frame_and_a_guided_frame_get_different_colours(conn, cfg):
    """Green once every gate is passed, amber while there is still an instruction: the
    patient can see the system is satisfied without reading the words."""
    pub = Publisher(conn, cfg)
    grey = np.full((720, 1280, 3), 128, dtype=np.uint8)
    box = (0.25, 0.25, 0.75, 0.75)
    good = _preview(pub, cfg, grey, box, True, at=T0)
    poor = _preview(pub, cfg, grey, box, False, at=T0 + 10)
    edge = (int(0.25 * good.shape[0]), int(0.5 * good.shape[1]))
    assert not np.array_equal(good[edge], poor[edge])


def test_a_box_outside_the_frame_is_clipped_not_crashed(conn, cfg):
    pub = Publisher(conn, cfg)
    grey = np.full((480, 640, 3), 128, dtype=np.uint8)
    assert pub.write_preview(grey, (-0.5, -0.5, 1.5, 1.5), T0, True) is True
    # A degenerate box draws nothing rather than raising.
    assert pub.write_preview(grey, (0.8, 0.8, 0.2, 0.2), T0 + 10, True) is True


def test_moving_numbers_do_not_rewrite_the_row(conn, cfg):
    """Telemetry changes on every frame; the row must still be written on change only.

    Letting blur and yaw into the comparison would turn one write per state change into
    fifteen writes a second onto the SD card the kiosk polls.
    """
    pub = Publisher(conn, cfg)
    assert pub.publish("GUIDING", "STEP_CLOSER",
                       payload={"telemetry": {"blur": 41}}, now=T0) == 1
    assert pub.publish("GUIDING", "STEP_CLOSER",
                       payload={"telemetry": {"blur": 44}}, now=T0 + 0.1) is None
    assert pub.publish("GUIDING", "STEP_CLOSER",
                       payload={"telemetry": {"blur": 52}}, now=T0 + 0.2) is None
    # The heartbeat carries the newest numbers a moment later.
    assert pub.publish("GUIDING", "STEP_CLOSER",
                       payload={"telemetry": {"blur": 60}}, now=T0 + 0.6) == 2
    assert kiosk_ipc.read_state(conn, after_seq=1)["payload"]["telemetry"]["blur"] == 60


def test_a_real_change_still_writes_immediately(conn, cfg):
    pub = Publisher(conn, cfg)
    pub.publish("GUIDING", "STEP_CLOSER", payload={"telemetry": {"blur": 41}}, now=T0)
    assert pub.publish("GUIDING", "LOOK_STRAIGHT",
                       payload={"telemetry": {"blur": 41}}, now=T0 + 0.05) == 2


def test_the_board_numbers_ride_along_with_the_state(conn, cfg):
    pub = Publisher(conn, cfg)
    pub.set_device({"ram_mb": 2100, "temp_c": 48})
    pub.set_fps(12.44)
    pub.publish("IDLE", now=T0)
    payload = kiosk_ipc.read_state(conn, after_seq=0)["payload"]
    assert payload["device"] == {"ram_mb": 2100, "temp_c": 48}
    assert payload["telemetry"]["fps"] == 12.4


def test_the_heartbeat_refreshes_the_board_numbers(conn, cfg):
    """A heartbeat must not re-publish the readings taken when the state last changed."""
    pub = Publisher(conn, cfg)
    pub.set_device({"temp_c": 48})
    pub.publish("AWAIT_NURSE", payload={"decision": "review_required"}, now=T0)
    pub.set_device({"temp_c": 61})
    assert pub.heartbeat(now=T0 + 0.6) == 2
    payload = kiosk_ipc.read_state(conn, after_seq=1)["payload"]
    assert payload["device"]["temp_c"] == 61
    assert payload["decision"] == "review_required"
