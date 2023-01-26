import PySimpleGUI as sg
import cv2
from cursor_image import CursorImage


class ImageViewer:
    """
    GUI row of two images update representing a CursorImage.
    """

    def __init__(self):
        self._computer_element = sg.Image()
        self._original_element = sg.Image()

    def layout_row(self):
        return [self._original_element, self._computer_element]

    def update(self, image: CursorImage):
        self._update_image_data(image.original, self._original_element)
        self._update_image_data(image.computer, self._computer_element)

    @staticmethod
    def _update_image_data(data, element):
        png = cv2.imencode('.png', data)
        element.update(data=png[1].tobytes())

