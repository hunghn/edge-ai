import threading
import time

import cv2
import numpy as np
import pytest

from edgeface.pipeline.capture import (CaptureThread, FileSource, RingBuffer,
                                       source_from_config)
from edgeface.types import Frame


def frame(i):
    return Frame(i, float(i), np.zeros((4, 4, 3), dtype=np.uint8))


def test_ring_buffer_returns_only_newer_frames():
    ring = RingBuffer()
    assert ring.get_latest(after_id=-1, timeout=0.01) is None
    ring.put(frame(1))
    assert ring.get_latest(after_id=0, timeout=0.01).frame_id == 1
    assert ring.get_latest(after_id=1, timeout=0.01) is None      # nothing new yet


def test_ring_buffer_drops_instead_of_queueing():
    ring = RingBuffer()
    for i in range(1, 6):
        ring.put(frame(i))
    assert ring.get_latest(after_id=0, timeout=0.01).frame_id == 5   # newest, not oldest
    assert ring.dropped == 4
    assert ring.received == 5


def test_ring_buffer_wakes_a_waiting_consumer():
    ring = RingBuffer()
    got = []

    def consume():
        got.append(ring.get_latest(after_id=0, timeout=2.0))

    reader = threading.Thread(target=consume)
    reader.start()
    time.sleep(0.05)
    ring.put(frame(7))
    reader.join(2.0)
    assert got and got[0].frame_id == 7


def test_slow_consumer_always_sees_the_latest_frame():
    """The engine must never fall behind the camera by more than one frame."""
    ring = RingBuffer()
    seen = []
    stop = threading.Event()

    def produce():
        i = 0
        while not stop.is_set():
            i += 1
            ring.put(frame(i))
            time.sleep(0.002)          # ~500 FPS producer

    writer = threading.Thread(target=produce)
    writer.start()
    try:
        last = 0
        for _ in range(5):
            time.sleep(0.03)           # ~33 FPS consumer
            got = ring.get_latest(after_id=last, timeout=1.0)
            assert got is not None and got.frame_id > last
            seen.append(got.frame_id)
            last = got.frame_id
    finally:
        stop.set()
        writer.join(1.0)
    assert seen == sorted(seen)
    assert ring.dropped > 0            # frames were dropped, not queued


@pytest.fixture
def video(tmp_path):
    path = str(tmp_path / "clip.mp4")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 20.0, (64, 48))
    for i in range(10):
        writer.write(np.full((48, 64, 3), i * 20, dtype=np.uint8))
    writer.release()
    return path


def test_file_source_reads_then_reports_eof(video):
    source = FileSource(video).open()
    count = 0
    while source.read() is not None:
        count += 1
    assert count == 10 and source.eof is True
    source.release()


def test_file_source_loops(video):
    source = FileSource(video, loop=True).open()
    assert sum(1 for _ in range(15) if source.read() is not None) == 15
    assert source.eof is False
    source.release()


def test_capture_thread_fills_the_ring(video):
    thread = CaptureThread(FileSource(video), read_fail_max=2).start()
    got = thread.ring.get_latest(after_id=0, timeout=2.0)
    assert got is not None and got.image.shape == (48, 64, 3)
    thread.stop()
    assert not thread.is_running()


def test_source_from_config_rejects_unknown_kind():
    with pytest.raises(ValueError):
        source_from_config({"capture": {"source": "telepathy"}})
