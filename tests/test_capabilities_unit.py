from __future__ import annotations

from importlib import resources

import numpy as np
import pytest
from PIL import Image

from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_locator import CursorLocator
from autoangler.screen import ScreenBounds


def test_cursor_locator_finds_template_on_synthetic_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    template_path = resources.files("autoangler.assets").joinpath("minecraft_cursor.png")
    import cv2

    template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
    assert template is not None

    screen_h, screen_w = 400, 600
    screen = np.full((screen_h, screen_w), 255, dtype=np.uint8)

    top, left = 120, 220
    th, tw = template.shape[:2]
    screen[top : top + th, left : left + tw] = template

    rgb = np.dstack([screen, screen, screen])
    synthetic = Image.fromarray(rgb, mode="RGB")

    monkeypatch.setattr("autoangler.cursor_locator.ImageGrab.grab", lambda: synthetic)
    monkeypatch.setattr(
        "autoangler.cursor_locator.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=10000, bottom=10000),
    )

    center = CursorLocator().locate()
    assert center == (left + tw // 2, top + th // 2)


def test_cursor_camera_clamps_bbox_to_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = CursorCamera(magnification=1)

    captured = {}

    def fake_grab(*, bbox):  # type: ignore[no-untyped-def]
        captured["bbox"] = bbox
        arr = np.full((30, 30, 3), 255, dtype=np.uint8)
        return Image.fromarray(arr, mode="RGB")

    monkeypatch.setattr("autoangler.cursor_camera.ImageGrab.grab", fake_grab)
    monkeypatch.setattr(
        "autoangler.cursor_camera.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=100, bottom=100),
    )

    # Cursor position chosen so bbox would extend above/left without clamping.
    _ = camera.capture((5, 5))
    assert captured["bbox"][0] >= 0
    assert captured["bbox"][1] >= 0


def test_cursor_camera_raises_if_bbox_outside_displays(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = CursorCamera(magnification=1)
    monkeypatch.setattr(
        "autoangler.cursor_camera.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=100, bottom=100),
    )

    with pytest.raises(OSError, match="does not intersect any displays"):
        _ = camera.capture((10000, 10000))
