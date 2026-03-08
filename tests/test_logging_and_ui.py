from __future__ import annotations

import json
import logging
from pathlib import Path

from pynput import keyboard

from autoangler.gui_tk import (
    AutoFishTkApp,
    hotkey_hint_text,
    line_state_text,
    tracking_status_text,
)
from autoangler.line_watcher import LineWatcher
from autoangler.logging_utils import (
    build_session_capture_path,
    build_session_log_path,
)


def test_build_session_log_path_uses_timestamped_session_name(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "20260307-160455")
    assert path == tmp_path / "sessions" / "20260307-160455.log"


def test_build_session_log_path_uses_log_extension(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "session-1")
    assert path.suffix == ".log"


def test_build_session_capture_path_uses_session_log_stem(tmp_path: Path) -> None:
    log_path = tmp_path / "sessions" / "20260307-211730.log"

    path = build_session_capture_path(log_path, "manual")

    assert path == tmp_path / "sessions" / "20260307-211730-manual.png"


def test_logging_utils_exposes_video_and_mark_path_builders() -> None:
    import autoangler.logging_utils as logging_utils

    assert hasattr(logging_utils, "build_session_video_path")
    assert hasattr(logging_utils, "build_session_mark_dir")


def test_hotkey_hint_text_includes_expected_keys() -> None:
    text = hotkey_hint_text(hotkeys_enabled=True)
    assert "M" in text
    assert "R" in text
    assert "F7" in text
    assert "F8" in text
    assert "F12" in text
    assert "F9" in text
    assert "ESC" in text
    assert "F10" in text


def test_hotkey_hint_text_reports_when_hotkeys_disabled() -> None:
    text = hotkey_hint_text(hotkeys_enabled=False)
    assert "disabled" in text.lower()


def test_line_state_text_reports_in_and_out() -> None:
    assert line_state_text(is_line_out=False) == "Line: In"
    assert line_state_text(is_line_out=True) == "Line: Out"


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


def test_on_key_press_routes_m_to_manual_mark() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    def marker() -> None:
        return None

    app._root = FakeRoot()
    app._mark_bite = marker  # type: ignore[method-assign]

    app._on_key_press(keyboard.KeyCode.from_char("m"))

    assert calls == [(0, marker)]


def test_on_key_press_routes_r_to_manual_reel() -> None:
    app = AutoFishTkApp()
    calls: list[tuple[int, object]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            calls.append((delay_ms, callback))

    def marker() -> None:
        return None

    app._root = FakeRoot()
    app._mark_reel = marker  # type: ignore[attr-defined]

    app._on_key_press(keyboard.KeyCode.from_char("r"))

    assert calls == [(0, marker)]


def test_load_window_geometry_uses_saved_geometry(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    state_path = tmp_path / "window.json"
    state_path.write_text(json.dumps({"geometry": "900x500+120+340"}))
    monkeypatch.setattr(app, "_window_state_path", lambda: state_path)

    geometry = app._load_window_geometry()

    assert geometry == "900x500+120+340"


def test_save_window_geometry_writes_state_file(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp()
    state_path = tmp_path / "window.json"
    monkeypatch.setattr(app, "_window_state_path", lambda: state_path)

    class FakeRoot:
        @staticmethod
        def geometry() -> str:
            return "900x500+120+340"

    app._root = FakeRoot()

    path = app._save_window_geometry()

    assert path == state_path
    assert json.loads(state_path.read_text()) == {"geometry": "900x500+120+340"}


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
