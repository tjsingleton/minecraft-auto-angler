from __future__ import annotations

import threading

import cv2
import numpy as np

from autoangler.async_pipeline import RecordingWorker
from autoangler.session_recorder import SessionRecorder


def test_real_vision_worker_keeps_newest_pending_frame(replay):
    replay.start()
    replay.advance(3000)
    replay.capture_release.clear()
    replay.app._submit_vision_request(now=replay.root.now)
    assert replay.capture_started.wait(timeout=5)
    try:
        replay.advance(110)
        replay.app._submit_vision_request(now=replay.root.now)
        replay.advance(110)
        replay.scene("gone")
        replay.app._submit_vision_request(now=replay.root.now)
    finally:
        replay.capture_release.set()
    worker = replay.app._vision_worker
    worker.close()
    assert not worker._thread.is_alive()
    results = worker.poll_results()
    replay.results.extend(results)
    assert [result.seq for result in results] == [1, 3]
    assert [result.line_pixels for result in results] == [60, 0]
    assert worker.dropped_frames == 1
    for result in results:
        replay.deliver(result)
    assert replay.state["catches"] == 1
    assert len(replay.clicks) == 2


def test_recording_pressure_preserves_controls_copies_and_drains_on_close(tmp_path):
    started, release = threading.Event(), threading.Event()
    recorded = []

    class BlockedRecorder(SessionRecorder):
        def record_frame(self, *, now, raw_window_frame, debug_frame):
            if now == 1:
                started.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("Recorder was not released")
            recorded.append((now, int(raw_window_frame[0, 0])))
            super().record_frame(
                now=now, raw_window_frame=raw_window_frame, debug_frame=debug_frame
            )

    log_path = tmp_path / "pressure.log"
    worker = RecordingWorker(log_path=log_path, queue_capacity=1, recorder_factory=BlockedRecorder)
    frame = np.full((24, 32), 10, dtype=np.uint8)
    screenshot = tmp_path / "screenshot.png"
    try:
        worker.enqueue_frame(now=1, raw_window_frame=frame, debug_frame=frame)
        assert started.wait(timeout=5)
        frame[:] = 20
        worker.enqueue_frame(now=2, raw_window_frame=frame, debug_frame=frame)
        worker.enqueue_screenshot(path=screenshot, image=frame)
        worker.enqueue_mark(label="manual", now=2)
        frame[:] = 30
        worker.enqueue_frame(now=3, raw_window_frame=frame, debug_frame=frame)
        frame[:] = 40
        worker.enqueue_frame(now=4, raw_window_frame=frame, debug_frame=frame)
        frame[:] = 250
    finally:
        release.set()
        worker.close()
    worker.close()
    assert not worker._thread.is_alive()
    assert recorded == [(1, 10), (4, 40)]
    assert worker.dropped_frames == 2
    assert worker.queue_depth == 0
    events = worker.poll_events()
    assert [event.kind for event in events] == [
        "drop_notice",
        "drop_notice",
        "screenshot_saved",
        "mark_saved",
        "closed",
    ]
    assert int(cv2.imread(str(screenshot), cv2.IMREAD_GRAYSCALE)[0, 0]) == 20
    clip = tmp_path / "pressure-manual-00"
    assert len(list(clip.glob("*.png"))) == 4
    assert int(cv2.imread(str(clip / "frame-000-window.png"), cv2.IMREAD_GRAYSCALE)[0, 0]) == 10
    assert int(cv2.imread(str(clip / "frame-001-window.png"), cv2.IMREAD_GRAYSCALE)[0, 0]) == 40
    for label in ("window", "debug"):
        video = cv2.VideoCapture(str(tmp_path / f"pressure-{label}.mp4"))
        try:
            assert video.isOpened()
            decoded = []
            while True:
                ok, image = video.read()
                if not ok:
                    break
                decoded.append(image)
            assert len(decoded) == 2
            assert all(image.shape[:2] == (24, 32) for image in decoded)
        finally:
            video.release()
    worker.enqueue_frame(now=5, raw_window_frame=frame, debug_frame=frame)
    worker.enqueue_screenshot(path=tmp_path / "after-close.png", image=frame)
    assert recorded == [(1, 10), (4, 40)]
    assert not (tmp_path / "after-close.png").exists()
