from __future__ import annotations

import cv2
import numpy as np
from PIL import ImageGrab

from autoangler.cursor_image import CursorImage
from autoangler.screen import get_virtual_screen_bounds


class CursorCamera:
    """
    Takes an image of directly below the position of the cursor.
    """

    def __init__(self, magnification: int = 1) -> None:
        self._magnification = magnification

    def capture(self, cursor_position: tuple[int, int] | tuple[float, float]) -> CursorImage:
        """
        Capture image below the cursor, hopefully of the fishing bobber.
        """
        bbox = self.bounding_box(cursor_position)
        bounds = get_virtual_screen_bounds()
        if bounds is not None:
            clamped = bounds.clamp_bbox(bbox)
            if clamped is None:
                raise OSError(f"Capture bbox {bbox} does not intersect any displays.")
            bbox = clamped

        capture = ImageGrab.grab(bbox=bbox)
        original = self.post_process(capture)

        computer = np.clip(original, 0, 1) * 255
        black_pixel_count = int(np.sum(computer == 0))

        return CursorImage(
            original=original, computer=computer, black_pixel_count=black_pixel_count
        )

    def post_process(self, image) -> cv2.Mat:
        """
        Convert to grayscale and enlarge.
        """
        processed = np.array(image)
        processed = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
        processed = cv2.resize(
            processed,
            None,
            fx=self._magnification,
            fy=self._magnification,
            interpolation=cv2.INTER_CUBIC,
        )
        return processed

    @staticmethod
    def bounding_box(cursor_position) -> tuple[int, int, int, int]:
        """
        Calculates the bounding box from the cursor position of where the fishing bobber should be.
        """
        mx, my = cursor_position
        x = int(mx) - 15
        y = int(my) + 15
        return x, y, x + 30, y + 30

    def blank(self) -> CursorImage:
        """
        All white image placeholder.
        """
        length = self._magnification * 30
        empty_image = np.full((length, length), 255, dtype=np.uint8)
        return CursorImage(original=empty_image, computer=empty_image, black_pixel_count=0)
