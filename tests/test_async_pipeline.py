from __future__ import annotations

import threading
from pathlib import Path
from time import monotonic, sleep

import numpy as np

from autoangler.async_pipeline import RecordingWorker, VisionRequest, VisionResult, VisionWorker
from autoangler.cursor_image import CursorImage


def test_recording_worker_saves_screenshot_and_emits_event(tmp_path: Path) -> None:
    worker = RecordingWorker(log_path=tmp_path / "sessions" / "s" / "s.log")
    image = np.full((4, 4), 7, dtype=np.uint8)
    path = tmp_path / "sessions" / "s" / "s-recording-00.png"

    worker.enqueue_screenshot(path=path, image=image)
    worker.close()

    events = worker.poll_events()

    assert path.exists()
    assert any(event.kind == "screenshot_saved" and event.path == path for event in events)
    assert events[-1].kind == "closed"


def test_recording_worker_drops_oldest_frame_when_queue_is_full(tmp_path: Path) -> None:
    release = threading.Event()
    recorded: list[float] = []

    class BlockingRecorder:
        window_video_path = Path("window.mp4")
        debug_video_path = Path("debug.mp4")

        def __init__(self, _log_path: Path) -> None:
            return None

        def record_frame(self, *, now: float, raw_window_frame, debug_frame) -> None:
            recorded.append(now)
            if now == 1.0:
                release.wait(timeout=2)

        def mark(self, label: str, *, now: float) -> Path:
            return tmp_path / f"{label}-{int(now)}"

        def finish_clips(self) -> None:
            return None

        def close(self) -> None:
            return None

    worker = RecordingWorker(
        log_path=tmp_path / "sessions" / "s" / "s.log",
        queue_capacity=1,
        recorder_factory=BlockingRecorder,
    )
    frame = np.zeros((4, 4), dtype=np.uint8)

    worker.enqueue_frame(now=1.0, raw_window_frame=frame, debug_frame=frame)
    sleep(0.05)
    worker.enqueue_frame(now=2.0, raw_window_frame=frame, debug_frame=frame)
    worker.enqueue_frame(now=3.0, raw_window_frame=frame, debug_frame=frame)
    release.set()
    worker.close()

    events = worker.poll_events()

    assert recorded == [1.0, 3.0]
    assert any(event.kind == "drop_notice" and event.dropped_frames == 1 for event in events)


def test_vision_worker_overwrites_pending_request_with_newest() -> None:
    started = threading.Event()
    release = threading.Event()
    seen: list[int] = []

    def processor(request: VisionRequest) -> VisionResult:
        seen.append(request.seq)
        if request.seq == 1:
            started.set()
            release.wait(timeout=2)
        blank = np.zeros((4, 4), dtype=np.uint8)
        return VisionResult(
            epoch=request.epoch,
            seq=request.seq,
            completed_at=monotonic(),
            window_frame=blank,
            main_preview_frame=blank,
            tracking_preview=CursorImage(original=blank, computer=blank, black_pixel_count=0),
            debug_composite=np.zeros((4, 8, 3), dtype=np.uint8),
            rod_in_hand=False,
            line_candidate=None,
            line_pixels=0,
            suggested_tracking_box=None,
            suggested_detection_box=None,
            capture_ms=1.0,
            detect_ms=2.0,
            annotate_ms=3.0,
            capture_error=None,
        )

    worker = VisionWorker(processor=processor)
    worker.submit(_vision_request(seq=1))
    assert started.wait(timeout=2)
    worker.submit(_vision_request(seq=2))
    worker.submit(_vision_request(seq=3))
    release.set()
    worker.close()

    results = worker.poll_results()

    assert seen == [1, 3]
    assert [result.seq for result in results] == [1, 3]
    assert worker.dropped_frames == 1


def _vision_request(*, seq: int, epoch: int = 1) -> VisionRequest:
    return VisionRequest(
        epoch=epoch,
        seq=seq,
        submitted_at=monotonic(),
        minecraft_window=None,
        fishing_roi=None,
        tracking_box=None,
        detection_box=None,
        is_fishing=True,
        is_line_out=True,
    )
