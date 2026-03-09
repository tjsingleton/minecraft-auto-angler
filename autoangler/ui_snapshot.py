from __future__ import annotations

from pathlib import Path
from typing import Callable

from PIL import Image, ImageGrab

from autoangler.screen import ScreenBounds, get_virtual_screen_bounds

DEFAULT_SNAPSHOT_BOUNDS = ScreenBounds(left=0, top=0, right=1280, bottom=800)


def capture_ui_screenshot(
    output_path: Path,
    *,
    grab_image: Callable[[tuple[int, int, int, int]], Image.Image] = ImageGrab.grab,
) -> Path:
    bounds = get_virtual_screen_bounds() or DEFAULT_SNAPSHOT_BOUNDS
    bbox = bounds.clamp_bbox((bounds.left, bounds.top, bounds.right, bounds.bottom))
    if bbox is None:
        bbox = (
            DEFAULT_SNAPSHOT_BOUNDS.left,
            DEFAULT_SNAPSHOT_BOUNDS.top,
            DEFAULT_SNAPSHOT_BOUNDS.right,
            DEFAULT_SNAPSHOT_BOUNDS.bottom,
        )

    image = grab_image(bbox)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path
