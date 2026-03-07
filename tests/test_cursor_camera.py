from __future__ import annotations

from autoangler.cursor_camera import CursorCamera


def test_bounding_box() -> None:
    bbox = CursorCamera.bounding_box((100, 200))
    assert bbox == (85, 215, 115, 245)


def test_blank_dimensions() -> None:
    camera = CursorCamera(magnification=10)
    blank = camera.blank()
    assert blank.original.shape == (300, 300)
