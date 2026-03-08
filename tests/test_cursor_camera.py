from __future__ import annotations

import numpy as np
from PIL import Image

from autoangler.cursor_camera import CursorCamera


def test_bounding_box() -> None:
    bbox = CursorCamera.bounding_box((100, 200))
    assert bbox == (85, 215, 115, 245)


def test_blank_dimensions() -> None:
    camera = CursorCamera(magnification=10)
    blank = camera.blank()
    assert blank.original.shape == (300, 300)


def test_post_process_can_skip_magnification() -> None:
    camera = CursorCamera(magnification=10)
    image = Image.fromarray(np.full((20, 40, 3), 255, dtype=np.uint8))

    processed = camera.post_process(image, magnify=False)

    assert processed.shape == (20, 40)
