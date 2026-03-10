from __future__ import annotations

from importlib import resources

import cv2
import numpy as np


class PauseMenuDetector:
    def __init__(self, *, match_threshold: float = 0.8) -> None:
        template_path = resources.files("autoangler.assets").joinpath(
            "pause_menu_options_template.png"
        )
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise FileNotFoundError(f"Could not load pause-menu template: {template_path!s}")

        self._templates: list[np.ndarray] = []
        for scale in (0.9, 1.0, 1.1):
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

    def detect(self, frame: np.ndarray) -> bool:
        gray = _to_gray(frame)
        search = _search_crop(gray)
        best_score = 0.0

        for template in self._templates:
            if template.shape[0] > search.shape[0] or template.shape[1] > search.shape[1]:
                continue
            result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
            _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
            best_score = max(best_score, float(max_val))

        return best_score >= self._match_threshold


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame.copy()


def _search_crop(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    left = int(width * 0.2)
    right = int(width * 0.8)
    top = 0
    bottom = int(height * 0.7)
    return frame[top:bottom, left:right]
