from __future__ import annotations

from pathlib import Path

from autoangler.gui_tk import hotkey_hint_text
from autoangler.logging_utils import build_session_log_path


def test_build_session_log_path_uses_timestamped_session_name(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "20260307-160455")
    assert path == tmp_path / "sessions" / "20260307-160455.log"


def test_build_session_log_path_uses_log_extension(tmp_path: Path) -> None:
    path = build_session_log_path(tmp_path, "session-1")
    assert path.suffix == ".log"


def test_hotkey_hint_text_includes_expected_keys() -> None:
    text = hotkey_hint_text(hotkeys_enabled=True)
    assert "F12" in text
    assert "ESC" in text
    assert "F10" in text


def test_hotkey_hint_text_reports_when_hotkeys_disabled() -> None:
    text = hotkey_hint_text(hotkeys_enabled=False)
    assert "disabled" in text.lower()
