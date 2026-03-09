from __future__ import annotations

from importlib import resources

import cv2
import numpy as np

from autoangler.minecraft_window import WindowInfo


def selected_slot_box(window: WindowInfo) -> tuple[int, int, int, int]:
    search_width = max(120, int(window.width * 0.42))
    search_height = max(48, int(window.height * 0.14))
    left = window.left + max(0, (window.width - search_width) // 2)
    top = window.top + window.height - search_height - max(8, int(window.height * 0.02))
    right = min(window.left + window.width, left + search_width)
    bottom = min(window.top + window.height, top + search_height)
    return left, top, right, bottom


class RodDetector:
    def __init__(self, *, match_threshold: float = 0.45) -> None:
        template_path = resources.files("autoangler.assets").joinpath(
            "fishing_rod_slot_template.png"
        )
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"Could not load rod template image: {template_path!s}")

        self._templates: list[np.ndarray] = []
        for scale in (0.8, 1.0, 1.2):
            scaled = cv2.resize(
                template,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_LINEAR,
            )
            if scaled.size:
                self._templates.append(scaled)
        self._match_threshold = match_threshold

    def detect(self, frame: np.ndarray, *, window: WindowInfo) -> bool:
        x1, y1, x2, y2 = selected_slot_box(window)
        crop = frame[y1 - window.top : y2 - window.top, x1 - window.left : x2 - window.left]
        if crop.size == 0:
            return False
        if crop.ndim == 3:
            crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        best_score = 0.0
        for template in self._templates:
            if template.shape[0] > crop.shape[0] or template.shape[1] > crop.shape[1]:
                continue
            result = cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
            best_score = max(best_score, float(max_val))

        return best_score >= self._match_threshold
