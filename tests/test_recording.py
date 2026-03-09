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
    app._close_recording_worker()

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
    assert "source,training_label,rod_in_hand,catch_count" in content
    assert ",tick,1,1,50," in content
    assert ",system,,0,0" in content


def test_append_profile_row_writes_stage_timings(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "s" / "s.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._is_fishing = True
    app._is_line_out = True
    app._line_pixels = 50
    app._line_watcher.observe(200, active=True)
    app._line_watcher.observe(50, active=True)

    path = app._append_profile_row(
        now=1.0,
        total_ms=100.0,
        capture_ms=70.0,
        detect_ms=10.0,
        preview_ms=15.0,
        record_ms=5.0,
    )

    assert path == tmp_path / "sessions" / "s" / "s-profile.csv"
    assert path.exists()
    header, row = path.read_text().splitlines()
    assert "vision_age_ms" in header
    assert "vision_dropped_frames" in header
    assert "record_queue_depth" in header
    assert "record_dropped_frames" in header
    assert row.endswith(",100.0,70.0,10.0,15.0,5.0,0.0,0,0,0,50,80")


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
    assert ",manual,,0,0" in path.read_text()


def test_manual_action_reels_when_line_is_out(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._is_line_out = True
    app._auto_strafe_enabled = False
    app._line_pixels = 77
    actions: list[str] = []
    delayed_calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            delayed_calls.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda **_kwargs: actions.append("reel"))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    path = app._manual_action()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",training_reel,1,1,77," in path.read_text()
    assert ",training,miss,0,0" in path.read_text()
    assert actions == ["reel"]
    assert len(delayed_calls) == 1
    delay_ms, callback = delayed_calls[0]
    assert 300 <= delay_ms <= 1000
    assert callback is app._cast


def test_manual_action_reels_with_detector_hit_label_when_line_is_out(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._is_line_out = True
    app._bite_detected = True
    app._auto_strafe_enabled = False
    actions: list[str] = []
    delayed_calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            delayed_calls.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda **_kwargs: actions.append("reel"))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    path = app._manual_action()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",training_reel,1,1,0," in path.read_text()
    assert ",training,hit,0,0" in path.read_text()
    assert actions == ["reel"]
    assert len(delayed_calls) == 1
    delay_ms, callback = delayed_calls[0]
    assert 300 <= delay_ms <= 1000
    assert callback is app._cast


def test_manual_action_casts_when_line_is_in(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._is_line_out = False
    actions: list[str] = []

    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    path = app._manual_action()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",manual_cast,1,0,0," in path.read_text()
    assert ",manual,,0,0" in path.read_text()
    assert actions == ["cast"]


def test_training_mark_and_reel_records_detector_hit(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._is_fishing = True
    app._is_line_out = True
    app._bite_detected = True
    app._auto_strafe_enabled = False
    actions: list[str] = []
    delayed_calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            delayed_calls.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda **_kwargs: actions.append("reel"))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    path = app._training_mark_and_reel()

    assert path == tmp_path / "sessions" / "20260307-213938-trace.csv"
    assert ",training_reel,1,1,0," in path.read_text()
    assert ",training,hit,0,0" in path.read_text()
    assert actions == ["reel"]
    assert len(delayed_calls) == 1
    delay_ms, callback = delayed_calls[0]
    assert 300 <= delay_ms <= 1000
    assert callback is app._cast


def test_manual_action_skips_trace_when_recording_disabled(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._is_fishing = True
    app._is_line_out = True
    calls: list[str] = []

    monkeypatch.setattr(app, "_append_trace_row", lambda **_kwargs: calls.append("trace"))
    monkeypatch.setattr(app, "_reel_and_recast", lambda **_kwargs: None)

    app._manual_action()

    assert calls == []


def test_training_mark_and_reel_skips_trace_when_recording_disabled(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._is_fishing = True
    app._is_line_out = True
    calls: list[str] = []

    monkeypatch.setattr(app, "_append_trace_row", lambda **_kwargs: calls.append("trace"))
    monkeypatch.setattr(app, "_reel_and_recast", lambda **_kwargs: None)

    app._training_mark_and_reel()

    assert calls == []


def test_append_trace_row_includes_rod_state_and_catch_count(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._rod_in_hand = True
    app._catch_count = 3

    path = app._append_trace_row(
        now=1.0,
        event="rod_state",
        source="system",
    )

    assert path.read_text().splitlines()[1].endswith(",system,,1,3")


def test_append_trace_row_logs_event_summary(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._is_fishing = True
    app._is_line_out = False
    app._line_pixels = 12
    app._bite_detected = True
    app._rod_in_hand = True
    app._catch_count = 4
    messages: list[str] = []

    monkeypatch.setattr(
        "autoangler.gui_tk.logger.info",
        lambda message, *args: messages.append(message % args if args else message),
    )

    app._append_trace_row(
        now=12.5,
        event="strafe",
        source="auto_strafe",
        scheduled_delay_ms=487,
        strafe_direction="left",
        strafe_duration_ms=122,
    )

    assert messages == [
        "EVENT strafe source=auto_strafe is_fishing=1 is_line_out=0 line_pixels=12 "
        "trigger_pixels=0 weak_frames=0 bite_detected=1 rod_in_hand=1 catch_count=4 "
        "scheduled_delay_ms=487 strafe_direction=left strafe_duration_ms=122"
    ]


def test_append_trace_row_logs_tick_at_debug(monkeypatch) -> None:
    app = AutoFishTkApp()
    info_messages: list[str] = []
    debug_messages: list[str] = []

    monkeypatch.setattr(
        "autoangler.gui_tk.logger.info",
        lambda message, *args: info_messages.append(message % args if args else message),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.logger.debug",
        lambda message, *args: debug_messages.append(message % args if args else message),
    )

    app._append_trace_row(now=12.5, event="tick")

    assert info_messages == []
    assert debug_messages == [
        "EVENT tick source=system is_fishing=0 is_line_out=0 line_pixels=0 "
        "trigger_pixels=0 weak_frames=0 bite_detected=0 rod_in_hand=0 catch_count=0"
    ]


def test_stop_records_source_in_trace(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._recording_enabled = True
    app._is_fishing = True
    trace_calls: list[dict[str, object]] = []

    class FakeButton:
        def configure(self, **_kwargs) -> None:
            return None

    app._button = FakeButton()

    monkeypatch.setattr(
        app,
        "_append_trace_row",
        lambda **kwargs: trace_calls.append(kwargs) or Path("/tmp/trace.csv"),
    )

    app._stop(source="hotkey_esc")

    assert len(trace_calls) == 1
    assert trace_calls[0]["event"] == "stop"
    assert trace_calls[0]["source"] == "hotkey_esc"


def test_cast_increments_cast_counter(monkeypatch) -> None:
    app = AutoFishTkApp()
    callbacks: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            callbacks.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_use_rod", lambda: None)

    app._cast()

    assert app._cast_count == 1
    assert callbacks == [(3000, app._mark_line_out)]


def test_reel_and_recast_waits_before_cast(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._auto_strafe_enabled = False
    actions: list[str] = []
    delayed_calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            delayed_calls.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda **_kwargs: actions.append("reel"))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))

    app._reel_and_recast()

    assert actions == ["reel"]
    assert len(delayed_calls) == 1
    delay_ms, callback = delayed_calls[0]
    assert 300 <= delay_ms <= 1000
    assert callback is app._cast


def test_auto_bite_reel_increments_catch_counter() -> None:
    app = AutoFishTkApp()
    calls: list[str] = []

    class FakeRoot:
        def after(self, _delay_ms: int, _callback) -> None:
            return None

    app._root = FakeRoot()
    app._is_fish_on = lambda: True  # type: ignore[method-assign]
    app._should_capture_preview = lambda: False  # type: ignore[method-assign]
    app._reel_and_recast = lambda **_kwargs: calls.append("recast")  # type: ignore[method-assign]

    app._tick()

    assert calls == ["recast"]
    assert app._catch_count == 1
