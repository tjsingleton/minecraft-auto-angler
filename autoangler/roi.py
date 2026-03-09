from __future__ import annotations

from autoangler.minecraft_window import WindowInfo


def default_fishing_roi(window: WindowInfo) -> tuple[int, int, int, int]:
    left = window.left + int(window.width * 0.40)
    top = window.top + int(window.height * 0.25)
    right = window.left + int(window.width * 0.80)
    bottom = window.top + int(window.height * 0.75)
    return left, top, right, bottom


def clamp_roi_to_window(
    roi: tuple[int, int, int, int], window: WindowInfo
) -> tuple[int, int, int, int]:
    left, top, right, bottom = roi
    return (
        max(left, window.left),
        max(top, window.top),
        min(right, window.left + window.width),
        min(bottom, window.top + window.height),
    )


def window_relative_box(
    box: tuple[int, int, int, int], window: WindowInfo
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    return (
        left - window.left,
        top - window.top,
        right - window.left,
        bottom - window.top,
    )


def cursor_anchor_in_roi(
    window: WindowInfo, roi: tuple[int, int, int, int], *, y_offset: int = 15
) -> tuple[int, int]:
    roi_left, roi_top, _, _ = window_relative_box(roi, window)
    return (
        (window.width // 2) - roi_left,
        (window.height // 2) + y_offset - roi_top,
    )
