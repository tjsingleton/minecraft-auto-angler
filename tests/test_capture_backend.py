from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import numpy as np


class _FakeMSSShot:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def __array__(self, dtype=None, copy=None):  # type: ignore[no-untyped-def]
        del copy
        if dtype is None:
            return self._array
        return self._array.astype(dtype)


class _FakeMSSContext:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.monitors = [
            {"left": 0, "top": 0, "width": 20, "height": 10},
            {"left": 5, "top": 7, "width": 3, "height": 2},
        ]
        self._frames = list(frames)
        self.closed = False
        self.grab_calls: list[object] = []

    def grab(self, monitor):  # type: ignore[no-untyped-def]
        self.grab_calls.append(monitor)
        return _FakeMSSShot(self._frames.pop(0))

    def close(self) -> None:
        self.closed = True


def test_create_capture_backend_defaults_to_mss(monkeypatch) -> None:
    import autoangler.capture_backend as capture_backend

    class FakeMSSBackend:
        backend_name = "mss"

        def close(self) -> None:
            return None

    monkeypatch.delenv("AUTOANGLER_CAPTURE_BACKEND", raising=False)
    monkeypatch.setattr(capture_backend, "MSSCaptureBackend", FakeMSSBackend)

    backend = capture_backend.create_capture_backend()

    assert isinstance(backend, FakeMSSBackend)


def test_create_capture_backend_uses_pillow_when_requested(monkeypatch) -> None:
    import autoangler.capture_backend as capture_backend

    class FakePillowBackend:
        backend_name = "pil"

        def close(self) -> None:
            return None

    monkeypatch.setenv("AUTOANGLER_CAPTURE_BACKEND", "pil")
    monkeypatch.setattr(capture_backend, "PillowCaptureBackend", FakePillowBackend)

    backend = capture_backend.create_capture_backend()

    assert isinstance(backend, FakePillowBackend)


def test_mss_backend_converts_bgra_to_rgb(monkeypatch) -> None:
    frames = [
        np.array(
            [[[7, 6, 5, 255], [10, 9, 8, 255]]],
            dtype=np.uint8,
        )
    ]
    fake_context = _FakeMSSContext(frames)

    fake_mss_module = type(
        "FakeMSSModule",
        (),
        {"mss": lambda: fake_context},
    )
    monkeypatch.setitem(sys.modules, "mss", fake_mss_module)

    import autoangler.capture_backend as capture_backend

    importlib.reload(capture_backend)
    backend = capture_backend.MSSCaptureBackend()
    try:
        frame = backend.grab((5, 7, 8, 9))
    finally:
        backend.close()

    assert frame.tolist() == [[[5, 6, 7], [8, 9, 10]]]
    assert fake_context.grab_calls == [{"left": 5, "top": 7, "width": 3, "height": 2}]
    assert fake_context.closed is True


def test_run_capture_benchmark_appends_jsonld_results(tmp_path: Path) -> None:
    from autoangler.experiment_harness import run_capture_benchmark

    session_dir = tmp_path / "sessions" / "20260309-120000"
    session_dir.mkdir(parents=True)
    log_path = session_dir / "20260309-120000.log"
    profile_path = session_dir / "20260309-120000-profile.csv"
    trace_path = session_dir / "20260309-120000-trace.csv"
    experiment_log = tmp_path / "experiment-log.jsonld"

    log_path.write_text(
        "\n".join(
            [
                "2026-03-09 12:00:00 INFO __main__: Starting AutoAngler (log: /tmp/x.log)",
                (
                    "2026-03-09 12:00:01 INFO autoangler.gui_tk: Using Minecraft window "
                    "'Minecraft 1.21.11 - Multiplayer (3rd-party Server)' at "
                    "WindowInfo(title='Minecraft 1.21.11 - Multiplayer (3rd-party Server)', "
                    "left=0, top=33, width=1513, height=949, owner='java')"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    profile_path.write_text(
        "\n".join(
            [
                "time_s,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,record_ms,line_pixels,trigger_pixels",
                "1.0,1,1,100.0,80.0,10.0,5.0,5.0,10,5",
                "2.0,1,1,200.0,150.0,20.0,20.0,10.0,9,5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    trace_path.write_text(
        "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,"
        "bite_detected\n",
        encoding="utf-8",
    )

    result = run_capture_benchmark(
        session_log=log_path,
        session_profile=profile_path,
        backend_name="mss",
        session_trace=trace_path,
        experiment_log=experiment_log,
    )

    assert result["@type"] == "CaptureBackendRun"
    assert result["backend"] == "mss"
    assert result["windowTitle"] == "Minecraft 1.21.11 - Multiplayer (3rd-party Server)"
    assert result["avgCaptureMs"] == 115.0

    lines = experiment_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["@type"] == "CaptureBackendRun"
    assert payload["profileSummary"]["avg_capture_ms"] == 115.0
