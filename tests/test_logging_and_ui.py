from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from pynput import keyboard

from autoangler.gui_tk import (
    AutoFishTkApp,
    cast_ratio_text,
    catch_count_text,
    hotkey_hint_text,
    line_state_text,
    main_window_minsize,
    main_window_summary_text,
    normalized_main_window_geometry,
    tracking_status_text,
)
from autoangler.line_watcher import LineWatcher
from autoangler.logging_utils import (
    build_session_capture_path,
    build_session_log_path,
    build_session_profile_path,
)


def test_build_session_log_path_uses_timestamped_session_name(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "20260307-160455")
    assert path == (
        tmp_path / "sessions" / "20260307-160455" / "20260307-160455.log"
    )


def test_build_session_log_path_uses_log_extension(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "session-1")
    assert path.suffix == ".log"


def test_build_session_profile_path_uses_session_directory(tmp_path: Path) -> None:
    log_path = tmp_path / "sessions" / "20260308-010000" / "20260308-010000.log"

    path = build_session_profile_path(log_path)

    assert path == (
        tmp_path / "sessions" / "20260308-010000" / "20260308-010000-profile.csv"
    )


def test_build_session_capture_path_uses_session_log_stem(tmp_path: Path) -> None:
    log_path = tmp_path / "sessions" / "20260307-211730" / "20260307-211730.log"

    path = build_session_capture_path(log_path, "manual")

    assert path == (
        tmp_path / "sessions" / "20260307-211730" / "20260307-211730-manual.png"
    )


def test_logging_utils_exposes_video_and_mark_path_builders() -> None:
    import autoangler.logging_utils as logging_utils

    assert hasattr(logging_utils, "build_session_video_path")
    assert hasattr(logging_utils, "build_session_mark_dir")


def test_hotkey_hint_text_includes_expected_keys() -> None:
    text = hotkey_hint_text(hotkeys_enabled=True)
    assert "F7" in text
    assert "F8" in text
    assert "F12" in text
    assert "F9" in text
    assert "F10" in text
    assert "Cmd+Q" in text


def test_hotkey_hint_text_reports_when_hotkeys_disabled() -> None:
    text = hotkey_hint_text(hotkeys_enabled=False)
    assert "disabled" in text.lower()


def test_line_state_text_reports_in_and_out() -> None:
    assert line_state_text(is_line_out=False) == "Line: In"
    assert line_state_text(is_line_out=True) == "Line: Out"


def test_catch_count_text_is_number_only() -> None:
    assert catch_count_text(7) == "7"


def test_cast_ratio_text_reports_bites_over_casts() -> None:
    assert cast_ratio_text(bites=3, casts=11) == "3 / 11"


def test_main_window_minsize_tracks_preview_dimensions() -> None:
    width, height = main_window_minsize()

    assert width <= 400
    assert 320 <= height <= 340


def test_main_window_summary_text_uses_integer_tick_without_label() -> None:
    assert main_window_summary_text(fps=22.4, tick_ms=43.5) == "FPS 22.4 | 44ms"


def test_main_window_resize_policy_disables_manual_resize() -> None:
    assert AutoFishTkApp._main_window_resizable() == (False, False)


def test_normalized_main_window_geometry_keeps_saved_position_only() -> None:
    width, height = main_window_minsize()

    geometry = normalized_main_window_geometry("900x500+120+340")

    assert geometry == f"{width}x{height}+120+340"


def test_tracking_status_text_shows_weak_frame_progress_and_bite_state() -> None:
    watcher = LineWatcher()
    watcher.observe(200, active=True)
    watcher.observe(50, active=True)

    text = tracking_status_text(
        line_pixels=50,
        watcher=watcher,
        is_line_out=True,
        bite_detected=False,
        elapsed_s=12,
        tick_interval=7,
        duration_ms=4.2,
        avg_ms=5.1,
    )

    assert "line 50 <= " in text
    assert "weak:1/2" in text
    assert "out:1" in text
    assert "bite:0" in text


def test_maybe_save_debug_screenshot_writes_file_in_debug_mode(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-211730.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    logger = logging.getLogger("autoangler.gui_tk")
    original_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        path = app._maybe_save_debug_screenshot("calibrate")
    finally:
        logger.setLevel(original_level)

    assert path == tmp_path / "sessions" / "20260307-211730-calibrate-00.png"
    assert path.exists()


def test_maybe_save_debug_screenshot_skips_when_not_debug_mode(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-211730.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    logger = logging.getLogger("autoangler.gui_tk")
    original_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        path = app._maybe_save_debug_screenshot("calibrate")
    finally:
        logger.setLevel(original_level)

    assert path is None


def test_toggle_recording_flips_recording_state() -> None:
    app = AutoFishTkApp()

    assert app._recording_enabled is False

    app._toggle_recording()
    assert app._recording_enabled is True

    app._toggle_recording()
    assert app._recording_enabled is False


def test_toggle_topmost_flips_window_state_and_updates_root() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[str, bool]] = []

    class FakeRoot:
        def attributes(self, name: str, value: bool) -> None:
            calls.append((name, value))

    app._root = FakeRoot()

    app._toggle_topmost()
    app._toggle_topmost()

    assert calls == [("-topmost", False), ("-topmost", True)]


def test_auto_strafe_defaults_enabled() -> None:
    app = AutoFishTkApp()

    assert app._auto_strafe_enabled is True


def test_toggle_auto_strafe_uses_checkbox_state() -> None:
    app = AutoFishTkApp()

    class FakeVar:
        def __init__(self, value: bool) -> None:
            self._value = value

        def get(self) -> bool:
            return self._value

        def set(self, value: bool) -> None:
            self._value = value

    app._auto_strafe_var = FakeVar(False)

    app._toggle_auto_strafe()

    assert app._auto_strafe_enabled is False


def test_toggle_recording_closes_session_recorder_when_disabling() -> None:
    app = AutoFishTkApp()
    app._recording_enabled = True
    closed: list[str] = []

    class FakeRecorder:
        def close(self) -> None:
            closed.append("closed")

    app._session_recorder = FakeRecorder()  # type: ignore[assignment]

    app._toggle_recording()

    assert app._recording_enabled is False
    assert closed == ["closed"]
    assert app._session_recorder is None


def test_open_session_folder_uses_active_session_directory(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp()
    log_path = tmp_path / "sessions" / "20260307-211730.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    monkeypatch.setattr("autoangler.gui_tk.sys.platform", "darwin")
    calls: list[list[str]] = []

    def fake_run(args: list[str], check: bool) -> None:
        calls.append(args)

    monkeypatch.setattr(subprocess, "run", fake_run)

    path = app._open_session_folder()

    assert path == log_path.parent
    assert calls == [["open", str(log_path.parent)]]


def test_button_start_waits_five_seconds_before_tracking() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    class FakeButton:
        def __init__(self) -> None:
            self.text = ""

        def configure(self, *, text: str) -> None:
            self.text = text

    class FakeVar:
        def __init__(self) -> None:
            self.value = ""

        def set(self, value: str) -> None:
            self.value = value

    app._root = FakeRoot()
    app._button = FakeButton()
    app._status_var = FakeVar()
    app._ensure_tracking_context = lambda: True  # type: ignore[method-assign]

    app._start()

    assert calls == [(5000, app._cast_and_begin_tracking)]
    assert app._button.text == "Stop Fishing"
    assert app._status_var.value == "Starting in 5s... focus Minecraft"


def test_hotkey_start_skips_five_second_delay() -> None:
    app = AutoFishTkApp()
    calls: list[str] = []

    class FakeButton:
        def __init__(self) -> None:
            self.text = ""

        def configure(self, *, text: str) -> None:
            self.text = text

    app._root = object()
    app._button = FakeButton()
    app._ensure_tracking_context = lambda: True  # type: ignore[method-assign]
    app._cast_and_begin_tracking = lambda: calls.append("cast")  # type: ignore[method-assign]

    app._start_hotkey()

    assert calls == ["cast"]
    assert app._button.text == "Stop Fishing"


def test_hotkey_toggle_stops_when_already_fishing() -> None:
    app = AutoFishTkApp()
    calls: list[str] = []

    app._is_fishing = True
    app._stop = lambda: calls.append("stop")  # type: ignore[method-assign]

    app._toggle_fishing()

    assert calls == ["stop"]


def test_tick_uses_delayed_recast_after_bite() -> None:
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


def test_debug_details_text_includes_profile_metrics() -> None:
    app = AutoFishTkApp()
    app._last_tick_duration_ms = 11.2
    app._last_capture_duration_ms = 7.4
    app._last_detect_duration_ms = 2.6
    app._last_preview_duration_ms = 1.8
    app._last_record_duration_ms = 1.1
    app._last_effective_fps = 18.5
    app._last_rss_mb = 64.0

    text = app._debug_details_text()

    assert "perf:" in text
    assert "fps:18.5" in text
    assert "tick:11.2ms" in text
    assert "cap:7.4ms" in text
    assert "detect:2.6ms" in text
    assert "preview:1.8ms" in text
    assert "rec:1.1ms" in text
    assert "rss:64.0MB" in text


def test_debug_stats_text_groups_sections() -> None:
    app = AutoFishTkApp()
    app._recording_enabled = True
    app._rod_in_hand = True
    app._catch_count = 2

    text = app._debug_stats_text()

    assert "Status" in text
    assert "Detection" in text
    assert "Recording" in text
    assert "Performance" in text
    assert "catch_count: 2" in text
    assert "rod_in_hand: 1" in text


def test_maybe_log_profile_emits_periodic_profile_line(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._is_fishing = True
    app._last_tick_duration_ms = 11.2
    app._last_capture_duration_ms = 7.4
    app._last_record_duration_ms = 1.1
    app._last_effective_fps = 18.5
    app._last_rss_mb = 64.0
    messages: list[str] = []

    monkeypatch.setattr(
        "autoangler.gui_tk.logger.info",
        lambda message, *args: messages.append(message % args if args else message),
    )

    app._maybe_log_profile(now=20.0)

    assert any(message.startswith("PROFILE ") for message in messages)


def test_debug_details_text_reports_top_stage() -> None:
    app = AutoFishTkApp()
    app._last_tick_duration_ms = 100.0
    app._last_capture_duration_ms = 70.0
    app._last_detect_duration_ms = 10.0
    app._last_preview_duration_ms = 5.0
    app._last_record_duration_ms = 4.0

    text = app._debug_details_text()

    assert "top:capture" in text


def test_maybe_refresh_tracking_context_recalibrates_when_window_geometry_changes(
    monkeypatch,
) -> None:
    app = AutoFishTkApp()
    app._minecraft_window = type(
        "Window",
        (),
        {"title": "Minecraft", "left": 10, "top": 20, "width": 100, "height": 80},
    )()
    calls: list[str] = []
    new_window = type(
        "Window",
        (),
        {"title": "Minecraft", "left": 15, "top": 25, "width": 100, "height": 80},
    )()

    monkeypatch.setattr("autoangler.gui_tk.selected_minecraft_window", lambda: new_window)
    monkeypatch.setattr(app, "_refresh_tracking_context", lambda: calls.append("refresh"))

    app._maybe_refresh_tracking_context(now=10.0)

    assert calls == ["refresh"]


def test_debug_details_text_includes_recording_and_candidate_details() -> None:
    app = AutoFishTkApp()
    app._recording_enabled = True
    app._fishing_roi = (320, 147, 960, 500)
    app._tracking_box = (280, 210, 360, 290)
    app._line_pixels = 42
    app._last_capture_error = "boom"
    app._last_saved_capture_name = "recording-01.png"
    app._line_candidate = type(
        "Candidate",
        (),
        {"center": (66, 309), "bbox": (44, 305, 88, 314), "pixel_count": 181},
    )()

    text = app._debug_details_text()

    assert "recording:on" in text
    assert "roi:(320, 147, 960, 500)" in text
    assert "track:(280, 210, 360, 290)" in text
    assert "candidate:(66, 309)" in text
    assert "pixels:181" in text
    assert "line_px:42" in text
    assert "last_capture:recording-01.png" in text
    assert "last_error:boom" in text


def test_on_key_press_routes_f8_to_manual_action() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    def marker() -> None:
        return None

    app._root = FakeRoot()
    app._manual_action = marker  # type: ignore[method-assign]

    app._on_key_press(keyboard.Key.f8)

    assert calls == [(0, marker)]


def test_on_key_press_ignores_removed_f6_hotkey() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    app._root = FakeRoot()

    app._on_key_press(keyboard.Key.f6)

    assert calls == []


def test_on_key_press_routes_f10_to_debug_window_toggle() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    def toggle() -> None:
        return None

    app._root = FakeRoot()
    app._toggle_debug_window = toggle  # type: ignore[attr-defined]

    app._on_key_press(keyboard.Key.f10)

    assert calls == [(0, toggle)]


def test_on_key_press_ignores_removed_m_hotkey() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    app._root = FakeRoot()

    app._on_key_press(keyboard.KeyCode.from_char("m"))

    assert calls == []


def test_load_window_geometry_uses_saved_geometry(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    state_path = tmp_path / "window.json"
    state_path.write_text(json.dumps({"geometry": "900x500+120+340", "topmost": False}))
    monkeypatch.setattr(app, "_window_state_path", lambda: state_path)

    geometry = app._load_window_geometry()

    assert geometry == normalized_main_window_geometry("900x500+120+340")
    assert app._topmost_enabled is False


def test_load_window_geometry_prefers_saved_position(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    state_path = tmp_path / "window.json"
    state_path.write_text(
        json.dumps(
            {
                "geometry": "900x500+0+0",
                "position": "+120+340",
                "topmost": False,
            }
        )
    )
    monkeypatch.setattr(app, "_window_state_path", lambda: state_path)

    geometry = app._load_window_geometry()

    width, height = main_window_minsize()
    assert geometry == f"{width}x{height}+120+340"
    assert app._topmost_enabled is False


def test_save_window_geometry_writes_state_file(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    state_path = tmp_path / "window.json"
    monkeypatch.setattr(app, "_window_state_path", lambda: state_path)
    app._topmost_enabled = False

    class FakeRoot:
        @staticmethod
        def geometry() -> str:
            return "900x500+120+340"

    app._root = FakeRoot()

    path = app._save_window_geometry()

    assert path == state_path
    assert json.loads(state_path.read_text()) == {
        "geometry": "900x500+120+340",
        "position": "+120+340",
        "topmost": False,
    }


def test_sync_line_state_indicator_updates_var() -> None:
    app = AutoFishTkApp()

    class FakeVar:
        def __init__(self) -> None:
            self.value = ""

        def set(self, value: str) -> None:
            self.value = value

    fake_var = FakeVar()
    app._line_state_var = fake_var

    app._is_line_out = False
    app._sync_line_state_indicator()
    assert fake_var.value == "Line: In"

    app._is_line_out = True
    app._sync_line_state_indicator()
    assert fake_var.value == "Line: Out"
