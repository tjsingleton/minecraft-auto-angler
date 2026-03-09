from __future__ import annotations

import numpy as np

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


def test_main_preview_frame_uses_roi_only() -> None:
    app = AutoFishTkApp()
    app._tracking_box = (30, 40, 70, 90)
    app._detection_box = (35, 55, 60, 80)
    window_frame = np.full((220, 260), 255, dtype=np.uint8)
    roi_box = (40, 30, 180, 150)
    roi_frame = window_frame[30:150, 40:180]

    preview = app._build_main_preview_frame(window_frame, roi_box, roi_frame)

    assert preview.shape == (120, 140)


def test_main_preview_validates_rod_state_when_line_is_in() -> None:
    app = AutoFishTkApp()
    app._is_line_out = False
    app._rod_in_hand = True

    assert app._main_preview_is_valid() is True


def test_main_preview_requires_detection_context_when_line_is_out() -> None:
    app = AutoFishTkApp()
    app._is_line_out = True
    app._detection_box = (1, 2, 3, 4)
    app._line_pixels = 12

    assert app._main_preview_is_valid() is True
