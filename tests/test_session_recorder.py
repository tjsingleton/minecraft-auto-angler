from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest


def _load_session_recorder_module():
    try:
        return importlib.import_module("autoangler.session_recorder")
    except ModuleNotFoundError as exc:  # pragma: no cover - red phase
        pytest.fail(f"autoangler.session_recorder is missing: {exc}")


def test_session_recorder_writes_window_and_debug_videos(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_session_recorder_module()
    SessionRecorder = getattr(module, "SessionRecorder", None)
    assert SessionRecorder is not None

    writes: list[tuple[Path, tuple[int, int], int]] = []

    class FakeWriter:
        def __init__(self, path: str, _fourcc: int, _fps: float, size: tuple[int, int]) -> None:
            self.path = Path(path)
            self.size = size
            self.frames = 0

        def write(self, _frame: np.ndarray) -> None:
            self.frames += 1

        def release(self) -> None:
            writes.append((self.path, self.size, self.frames))

    monkeypatch.setattr(module.cv2, "VideoWriter", FakeWriter)
    monkeypatch.setattr(module.cv2, "VideoWriter_fourcc", lambda *_args: 0)

    recorder = SessionRecorder(tmp_path / "sessions" / "20260308-010000.log", fps=10.0)
    recorder.record_frame(
        now=1.0,
        raw_window_frame=np.full((20, 30), 255, dtype=np.uint8),
        debug_frame=np.zeros((10, 12), dtype=np.uint8),
    )
    recorder.record_frame(
        now=2.0,
        raw_window_frame=np.full((20, 30), 200, dtype=np.uint8),
        debug_frame=np.full((10, 12), 128, dtype=np.uint8),
    )
    recorder.close()

    assert writes == [
        (tmp_path / "sessions" / "20260308-010000-window.mp4", (30, 20), 2),
        (tmp_path / "sessions" / "20260308-010000-debug.mp4", (12, 10), 2),
    ]


def test_session_recorder_saves_mark_clip_series(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load_session_recorder_module()
    SessionRecorder = getattr(module, "SessionRecorder", None)
    assert SessionRecorder is not None

    class FakeWriter:
        def __init__(self, *_args) -> None:
            return None

        def write(self, _frame: np.ndarray) -> None:
            return None

        def release(self) -> None:
            return None

    monkeypatch.setattr(module.cv2, "VideoWriter", FakeWriter)
    monkeypatch.setattr(module.cv2, "VideoWriter_fourcc", lambda *_args: 0)

    recorder = SessionRecorder(
        tmp_path / "sessions" / "20260308-010000.log",
        fps=10.0,
        pre_frames=2,
        post_frames=1,
    )
    recorder.record_frame(
        now=1.0,
        raw_window_frame=np.full((20, 30), 255, dtype=np.uint8),
        debug_frame=np.zeros((10, 12), dtype=np.uint8),
    )
    recorder.record_frame(
        now=2.0,
        raw_window_frame=np.full((20, 30), 200, dtype=np.uint8),
        debug_frame=np.full((10, 12), 64, dtype=np.uint8),
    )

    clip_dir = recorder.mark("mark", now=2.0)
    recorder.record_frame(
        now=3.0,
        raw_window_frame=np.full((20, 30), 100, dtype=np.uint8),
        debug_frame=np.full((10, 12), 255, dtype=np.uint8),
    )
    recorder.close()

    assert clip_dir == tmp_path / "sessions" / "20260308-010000-mark-00"
    assert clip_dir.exists()
    assert sorted(path.name for path in clip_dir.glob("*.png")) == [
        "frame-000-debug.png",
        "frame-000-window.png",
        "frame-001-debug.png",
        "frame-001-window.png",
        "frame-002-debug.png",
        "frame-002-window.png",
    ]
