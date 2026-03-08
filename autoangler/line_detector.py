from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class LineCandidate:
    center: tuple[int, int]
    bbox: tuple[int, int, int, int]
    pixel_count: int
    score: float


class FishingLineDetector:
    def __init__(self, *, contrast_threshold: int | None = None) -> None:
        threshold_env = os.environ.get("AUTOANGLER_LINE_DARKNESS_THRESHOLD", "").strip()
        if contrast_threshold is not None:
            self._black_threshold = contrast_threshold
        else:
            self._black_threshold = int(threshold_env) if threshold_env else 24
        self._min_pixel_count = 8
        self._max_pixel_count = 500
        self._min_length = 18.0
        self._max_thickness = 12.0
        self._min_aspect_ratio = 2.0
        self._kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))

    def threshold_dark_pixels(self, frame: np.ndarray) -> np.ndarray:
        return absolute_dark_mask(frame, black_threshold=self._black_threshold)

    def find_line(self, frame: np.ndarray) -> LineCandidate | None:
        thresholded = self.threshold_dark_pixels(frame)
        dark_mask = cv2.bitwise_not(thresholded)
        contours, _ = cv2.findContours(
            dark_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        frame_center = (thresholded.shape[1] / 2, thresholded.shape[0] / 2)
        best: LineCandidate | None = None

        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)
            if _touches_frame_edge(x, y, width, height, thresholded.shape):
                continue

            pixel_count = int(cv2.countNonZero(dark_mask[y : y + height, x : x + width]))
            if pixel_count < self._min_pixel_count or pixel_count > self._max_pixel_count:
                continue

            (_, _), (side_a, side_b), _ = cv2.minAreaRect(contour)
            major_axis = max(side_a, side_b)
            minor_axis = max(min(side_a, side_b), 1.0)

            if major_axis < self._min_length:
                continue
            if minor_axis > self._max_thickness:
                continue

            aspect_ratio = major_axis / minor_axis
            if aspect_ratio < self._min_aspect_ratio:
                continue

            center = (x + width // 2, y + height // 2)
            distance = abs(center[0] - frame_center[0]) + abs(center[1] - frame_center[1])
            score = (aspect_ratio * 100.0) + pixel_count - (distance * 0.25)

            candidate = LineCandidate(
                center=center,
                bbox=(x, y, x + width, y + height),
                pixel_count=pixel_count,
                score=score,
            )
            if best is None or candidate.score > best.score:
                best = candidate

        return best


def tracking_box_for_candidate(
    candidate: LineCandidate,
    frame_shape: tuple[int, ...],
    *,
    padding: int = 20,
    min_size: int = 60,
) -> tuple[int, int, int, int]:
    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = candidate.bbox
    half_size = int(
        max(
            min_size / 2,
            ((x2 - x1) / 2) + padding,
            ((y2 - y1) / 2) + padding,
        )
    )
    return centered_tracking_box(frame_shape, center=candidate.center, size=half_size * 2)


def centered_tracking_box(
    frame_shape: tuple[int, ...],
    *,
    center: tuple[int, int] | None = None,
    size: int = 80,
) -> tuple[int, int, int, int]:
    frame_height, frame_width = frame_shape[:2]
    if center is None:
        center = (frame_width // 2, frame_height // 2)

    half_size = max(1, size // 2)
    left = center[0] - half_size
    top = center[1] - half_size
    right = center[0] + half_size
    bottom = center[1] + half_size

    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > frame_width:
        left -= right - frame_width
        right = frame_width
    if bottom > frame_height:
        top -= bottom - frame_height
        bottom = frame_height

    left = max(0, left)
    top = max(0, top)
    right = min(frame_width, right)
    bottom = min(frame_height, bottom)

    return int(left), int(top), int(right), int(bottom)


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame.copy()


def local_contrast_mask(
    frame: np.ndarray,
    *,
    contrast_threshold: int = 12,
    kernel: np.ndarray | None = None,
) -> np.ndarray:
    gray = _to_gray(frame)
    kernel = kernel if kernel is not None else cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    enhanced = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)
    enhanced = cv2.GaussianBlur(enhanced, (3, 3), 0)
    _, thresholded = cv2.threshold(
        enhanced,
        contrast_threshold,
        255,
        cv2.THRESH_BINARY,
    )
    return cv2.bitwise_not(thresholded.astype(np.uint8))


def absolute_dark_mask(frame: np.ndarray, *, black_threshold: int = 32) -> np.ndarray:
    gray = _to_gray(frame)
    _, thresholded = cv2.threshold(
        gray,
        black_threshold,
        255,
        cv2.THRESH_BINARY,
    )
    return thresholded.astype(np.uint8)


def _touches_frame_edge(
    x: int, y: int, width: int, height: int, frame_shape: tuple[int, ...]
) -> bool:
    frame_height, frame_width = frame_shape[:2]
    return x <= 0 or y <= 0 or (x + width) >= frame_width or (y + height) >= frame_height
