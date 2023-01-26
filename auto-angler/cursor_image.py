import cv2
import numpy as np


class CursorImage:
    """
    The image data from the CursorCamera in both the original and computer version.

    Attributes:
        original (cv2.Mat): Human recognizable image
        computer (cv2.Mat): Simulated image of what the computer is looking for
        black_pixel_count: Number of black pixels
    """

    def __init__(self, original: cv2.Mat, computer: cv2.Mat, black_pixel_count: int):
        self.original = original
        self.computer = computer
        self.black_pixel_count = black_pixel_count
