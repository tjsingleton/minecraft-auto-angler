from __future__ import annotations

from autoangler.gui_tk import AutoFishTkApp


def test_preview_target_prefers_locked_cursor() -> None:
    app = AutoFishTkApp()
    app._cursor_position = (100, 200)
    assert app._preview_target() == (100, 200)


def test_preview_target_falls_back_to_active_window_center(monkeypatch) -> None:
    app = AutoFishTkApp()
    monkeypatch.setattr(app, "_get_active_window_center", lambda: (300, 400))
    monkeypatch.setattr(app, "_get_virtual_screen_center", lambda: (500, 600))
    assert app._preview_target() == (300, 400)


def test_preview_target_falls_back_to_virtual_screen_center(monkeypatch) -> None:
    app = AutoFishTkApp()
    monkeypatch.setattr(app, "_get_active_window_center", lambda: None)
    monkeypatch.setattr(app, "_get_virtual_screen_center", lambda: (500, 600))
    assert app._preview_target() == (500, 600)
