import cv2
import numpy as np
from PIL import ImageGrab
from cursor_image import CursorImage


class CursorCamera:
    """
    Takes an image of directly below the position of the cursor
    """

    def __init__(self, magnification: int = 1) -> None:
        """
        Args:
            magnification: How much to enlarge the image in postprocessing
        """
        self._magnification = magnification

    def capture(self, cursor_position) -> CursorImage:
        """
        Capture image below the cursor, hopefully of the fishing bobber
        Args:
            cursor_position: coordinates to the top left box surrounding the cursor

        Returns:
            CursorImage
        """
        bbox = self.bounding_box(cursor_position)
        capture = ImageGrab.grab(bbox=bbox)
        original = self.post_process(capture)

        # make image
        computer = np.clip(original, 0, 1) * 255
        black_pixel_count = int(np.sum(computer == 0))

        return CursorImage(original=original,
                           computer=computer,
                           black_pixel_count=black_pixel_count)

    def post_process(self, image) -> cv2.Mat:
        """
        Convert to grayscale and enlarge

        Args:
            image: source to process

        Returns: post processed image
        """
        processed = np.array(image)
        processed = cv2.cvtColor(processed, cv2.COLOR_BGR2GRAY)
        processed = cv2.resize(
            processed,
            None,
            fx=self._magnification,
            fy=self._magnification,
            interpolation=cv2.INTER_CUBIC
        )
        return processed

    @staticmethod
    def bounding_box(cursor_position):
        """
        Calculates the bounding box from the cursor position of where the fishing bobber should be

        Args:
            cursor_position: coordinates to the top left of a box surrounding the cursor

        Returns: rectangle below the cursor hopefully containing the bobber
        """
        mx, my = cursor_position
        x = mx - 15
        y = my + 15

        return x, y, x + 30, y + 30

    def blank(self):
        """
        All white image placeholder
        """
        length = self._magnification * 30
        empty_image = np.full((length, length), 255)
        return CursorImage(original=empty_image, computer=empty_image, black_pixel_count=0)
