from __future__ import annotations

import logging
import os
from importlib import resources

import cv2
import numpy as np
from PIL import ImageGrab

from autoangler.screen import get_virtual_screen_bounds

logger = logging.getLogger(__name__)


class CursorLocator:
    def __init__(self) -> None:
        threshold_env = os.environ.get("AUTOANGLER_CURSOR_THRESHOLD", "").strip()
        self._threshold = float(threshold_env) if threshold_env else 0.8

        scales_env = os.environ.get("AUTOANGLER_CURSOR_SCALES", "").strip()
        if scales_env:
            scales = [float(s.strip()) for s in scales_env.split(",") if s.strip()]
        else:
            scales = [1.0, 1.25, 1.5, 2.0]
        self._scales = [s for s in scales if s > 0]

        template_path = resources.files("autoangler.assets").joinpath("minecraft_cursor.png")
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"Could not load template image: {template_path!s}")

        self._templates: list[tuple[float, np.ndarray]] = []
        for scale in self._scales:
            if scale == 1.0:
                scaled = template
            else:
                scaled = cv2.resize(
                    template,
                    None,
                    fx=scale,
                    fy=scale,
                    interpolation=cv2.INTER_CUBIC,
                )
            if scaled.shape[0] < 2 or scaled.shape[1] < 2:
                continue
            self._templates.append((scale, scaled))

        self.last_best_val: float | None = None
        self.last_best_scale: float | None = None
        self.last_best_loc: tuple[int, int] | None = None

    def locate(self) -> tuple[int, int] | None:
        img = ImageGrab.grab()
        arr = np.array(img)  # convert the image to numpy array
        image = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

        best_val = None
        best_loc = None
        best_template = None
        best_scale = None

        for scale, template in self._templates:
            if template.shape[0] > image.shape[0] or template.shape[1] > image.shape[1]:
                continue

            result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)

            if best_val is None or max_val > best_val:
                best_val = float(max_val)
                best_loc = max_loc
                best_template = template
                best_scale = scale

        if best_val is None or best_loc is None or best_template is None or best_scale is None:
            logger.debug("Cursor locate: no candidate templates fit the screenshot.")
            self.last_best_val = None
            self.last_best_scale = None
            self.last_best_loc = None
            return None

        self.last_best_val = best_val
        self.last_best_scale = best_scale
        self.last_best_loc = (int(best_loc[0]), int(best_loc[1]))

        logger.debug(
            "Cursor locate: best_val=%.4f threshold=%.4f scale=%.2f loc=%s",
            best_val,
            self._threshold,
            best_scale,
            best_loc,
        )

        if best_val < self._threshold:
            return None

        height, width = best_template.shape[:2]
        center = (int(best_loc[0] + width / 2), int(best_loc[1] + height / 2))

        bounds = get_virtual_screen_bounds()
        if bounds is not None and not bounds.contains_point(center):
            return None

        return center
