import cv2
import numpy as np
from PIL import ImageGrab


class CursorLocator:
    # TODO This method has too many false positives
    def locate(self):
        img = ImageGrab.grab()
        arr = np.array(img)  # convert the image to numpy array
        image = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

        template = cv2.imread('minecraft_cursor.png', cv2.IMREAD_GRAYSCALE)
        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF)

        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        if max_val < 0.999:
            return None

        height, width = template.shape[:2]

        center = (max_loc[0] + width / 2, max_loc[1] + height / 2)

        return center
