from __future__ import annotations

from importlib import resources

import numpy as np
import pytest

from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_locator import CursorLocator
from autoangler.screen import ScreenBounds


class FakeCaptureBackend:
    def __init__(self, frame: np.ndarray) -> None:
        self._frame = frame
        self.calls: list[tuple[int, int, int, int] | None] = []

    def grab(self, bbox: tuple[int, int, int, int] | None = None) -> np.ndarray:
        self.calls.append(bbox)
        return self._frame.copy()

    def close(self) -> None:
        return None


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
    monkeypatch.setattr(
        "autoangler.cursor_locator.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=10000, bottom=10000),
    )

    center = CursorLocator(capture_backend=FakeCaptureBackend(rgb)).locate()
    assert center == (left + tw // 2, top + th // 2)


def test_cursor_camera_clamps_bbox_to_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = FakeCaptureBackend(np.full((30, 30, 3), 255, dtype=np.uint8))
    camera = CursorCamera(magnification=1, capture_backend=backend)

    monkeypatch.setattr(
        "autoangler.cursor_camera.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=100, bottom=100),
    )

    # Cursor position chosen so bbox would extend above/left without clamping.
    _ = camera.capture((5, 5))
    assert backend.calls[0] is not None
    assert backend.calls[0][0] >= 0
    assert backend.calls[0][1] >= 0


def test_cursor_camera_raises_if_bbox_outside_displays(monkeypatch: pytest.MonkeyPatch) -> None:
    camera = CursorCamera(
        magnification=1,
        capture_backend=FakeCaptureBackend(np.full((30, 30, 3), 255, dtype=np.uint8)),
    )
    monkeypatch.setattr(
        "autoangler.cursor_camera.get_virtual_screen_bounds",
        lambda: ScreenBounds(left=0, top=0, right=100, bottom=100),
    )

    with pytest.raises(OSError, match="does not intersect any displays"):
        _ = camera.capture((10000, 10000))
