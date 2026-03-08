from __future__ import annotations

from pathlib import Path

from autoangler.gui_tk import AutoFishTkApp


def test_maybe_record_frame_skips_when_not_fishing(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = False

    result = app._maybe_record_frame(now=1.0)

    assert result is None


def test_maybe_record_frame_saves_on_interval(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    monkeypatch.setenv("AUTOANGLER_RECORD_INTERVAL_MS", "1000")
    app._recording_enabled = True
    app._is_fishing = True
    app._last_recording_capture_at = 0.0

    first = app._maybe_record_frame(now=1.0)
    second = app._maybe_record_frame(now=1.5)
    third = app._maybe_record_frame(now=2.1)

    assert first == tmp_path / "sessions" / "20260307-213938-recording-00.png"
    assert first.exists()
    assert second is None
    assert third == tmp_path / "sessions" / "20260307-213938-recording-01.png"
    assert third.exists()


def test_append_trace_row_writes_csv(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._is_fishing = True
    app._is_line_out = True
    app._line_pixels = 50
    app._bite_detected = False
    app._line_watcher.observe(200, active=True)
    app._line_watcher.observe(50, active=True)

    path = app._append_trace_row(now=12.5, event="tick")

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert path.exists()
    content = path.read_text()
    assert (
        "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,"
        "bite_detected" in content
    )
    assert ",tick,1,1,50," in content


def test_mark_bite_appends_mark_event(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._line_pixels = 77

    path = app._mark_bite()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",mark,1,0,77," in path.read_text()


def test_mark_reel_appends_mark_reel_event_and_recasts(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._is_line_out = True
    app._line_pixels = 77
    actions: list[str] = []

    mark_reel = getattr(app, "_mark_reel", None)
    assert mark_reel is not None
    monkeypatch.setattr(app, "_reel", lambda: actions.append("reel"))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    path = mark_reel()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",mark_reel,1,1,77," in path.read_text()
    assert actions == ["reel", "cast"]
