from __future__ import annotations

from autoangler.minecraft_window import WindowInfo
from autoangler.roi import (
    clamp_roi_to_window,
    cursor_anchor_in_roi,
    default_fishing_roi,
    window_relative_box,
)


def test_default_fishing_roi_uses_smaller_lower_right_window_region() -> None:
    window = WindowInfo(title="Minecraft", left=100, top=100, width=1600, height=900)
    roi = default_fishing_roi(window)
    assert roi == (740, 325, 1380, 775)


def test_clamp_roi_to_window_bounds() -> None:
    window = WindowInfo(title="Minecraft", left=0, top=0, width=1000, height=700)
    roi = clamp_roi_to_window((900, 650, 1200, 900), window)
    assert roi == (900, 650, 1000, 700)


def test_window_relative_box_uses_window_origin() -> None:
    window = WindowInfo(title="Minecraft", left=18, top=30, width=1280, height=705)

    box = window_relative_box((530, 206, 1042, 558), window)

    assert box == (512, 176, 1024, 528)


def test_cursor_anchor_in_roi_tracks_window_center_with_offset() -> None:
    window = WindowInfo(title="Minecraft", left=18, top=30, width=1280, height=705)
    roi = (530, 206, 1042, 558)

    anchor = cursor_anchor_in_roi(window, roi, y_offset=15)

    assert anchor == (128, 191)
