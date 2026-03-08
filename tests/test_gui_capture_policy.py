from __future__ import annotations

from autoangler.gui_tk import AutoFishTkApp
from autoangler.minecraft_window import WindowInfo


def test_should_capture_preview_is_false_when_idle_without_context() -> None:
    app = AutoFishTkApp()
    assert app._should_capture_preview() is False


def test_should_capture_preview_is_true_while_fishing() -> None:
    app = AutoFishTkApp()
    app._is_fishing = True
    assert app._should_capture_preview() is True


def test_should_capture_preview_is_true_with_window_context() -> None:
    app = AutoFishTkApp()
    app._minecraft_window = WindowInfo(title="Minecraft", left=0, top=0, width=1000, height=700)
    app._fishing_roi = (100, 100, 400, 300)
    assert app._should_capture_preview() is True

