from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScreenBounds:
    """
    A virtual-screen bounding box in global coordinates.

    left, top, right, bottom are inclusive/exclusive like PIL's ImageGrab bbox.
    """

    left: int
    top: int
    right: int
    bottom: int

    def clamp_bbox(self, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
        left, top, right, bottom = bbox
        clamped_left = max(left, self.left)
        clamped_top = max(top, self.top)
        clamped_right = min(right, self.right)
        clamped_bottom = min(bottom, self.bottom)

        if clamped_right <= clamped_left or clamped_bottom <= clamped_top:
            return None

        return clamped_left, clamped_top, clamped_right, clamped_bottom

    def contains_point(self, point: tuple[int, int] | tuple[float, float]) -> bool:
        x, y = point
        return self.left <= x < self.right and self.top <= y < self.bottom


def get_virtual_screen_bounds() -> Optional[ScreenBounds]:
    """
    Best-effort detection of the virtual screen bounds.

    On macOS, this unions all active display bounds via Quartz.
    On other platforms, it falls back to the primary display size via pyautogui.
    """

    try:
        import sys

        if sys.platform == "darwin":
            from Quartz import (  # type: ignore[import-not-found]
                CGDisplayBounds,
                CGGetActiveDisplayList,
            )

            _max_displays = 32
            err, displays, display_count = CGGetActiveDisplayList(_max_displays, None, None)
            if err != 0 or display_count is None:
                return None

            left = top = None
            right = bottom = None
            for display_id in displays[: int(display_count)]:
                rect = CGDisplayBounds(display_id)
                display_left = int(rect.origin.x)
                display_top = int(rect.origin.y)
                display_right = display_left + int(rect.size.width)
                display_bottom = display_top + int(rect.size.height)

                left = display_left if left is None else min(left, display_left)
                top = display_top if top is None else min(top, display_top)
                right = display_right if right is None else max(right, display_right)
                bottom = display_bottom if bottom is None else max(bottom, display_bottom)

            if None in (left, top, right, bottom):
                return None

            return ScreenBounds(left=left, top=top, right=right, bottom=bottom)

        import pyautogui

        width, height = pyautogui.size()
        return ScreenBounds(left=0, top=0, right=int(width), bottom=int(height))
    except Exception:
        return None
