from __future__ import annotations

import cv2
import numpy as np

from autoangler.line_detector import FishingLineDetector, LineCandidate, tracking_box_for_candidate


def test_threshold_dark_pixels_keeps_dark_line_black() -> None:
    detector = FishingLineDetector()
    frame = np.full((80, 80), 255, dtype=np.uint8)
    cv2.line(frame, (10, 50), (60, 20), 0, 2)

    thresholded = detector.threshold_dark_pixels(frame)

    assert thresholded[5, 5] == 255
    assert thresholded[35, 35] == 0


def test_find_line_returns_thin_dark_segment() -> None:
    detector = FishingLineDetector()
    frame = np.full((200, 300), 255, dtype=np.uint8)
    cv2.line(frame, (110, 130), (170, 100), 0, 2)

    result = detector.find_line(frame)

    assert result is not None
    assert 120 <= result.center[0] <= 160
    assert 100 <= result.center[1] <= 130
    assert result.pixel_count > 0


def test_find_line_rejects_large_dark_regions() -> None:
    detector = FishingLineDetector()
    frame = np.full((200, 300), 255, dtype=np.uint8)
    frame[40:170, 100:220] = 0

    result = detector.find_line(frame)

    assert result is None


def test_threshold_dark_pixels_does_not_black_out_dim_scene() -> None:
    detector = FishingLineDetector()
    frame = np.full((80, 80), 55, dtype=np.uint8)
    cv2.line(frame, (10, 50), (60, 20), 20, 2)

    thresholded = detector.threshold_dark_pixels(frame)

    assert thresholded[5, 5] == 255
    assert thresholded[35, 35] == 0


def test_threshold_dark_pixels_ignores_dark_patch_that_is_not_true_black() -> None:
    detector = FishingLineDetector()
    frame = np.full((80, 80), 50, dtype=np.uint8)
    frame[10:20, 10:20] = 30
    cv2.line(frame, (10, 50), (60, 20), 0, 2)

    thresholded = detector.threshold_dark_pixels(frame)

    assert thresholded[15, 15] == 255
    assert thresholded[35, 35] == 0


def test_threshold_dark_pixels_ignores_dark_gray_line() -> None:
    detector = FishingLineDetector()
    frame = np.full((80, 80), 50, dtype=np.uint8)
    cv2.line(frame, (5, 10), (75, 10), 30, 2)
    cv2.line(frame, (5, 50), (75, 50), 0, 2)

    thresholded = detector.threshold_dark_pixels(frame)

    assert thresholded[10, 40] == 255
    assert thresholded[50, 40] == 0


def test_tracking_box_for_candidate_expands_and_clamps_to_frame() -> None:
    candidate = LineCandidate(
        center=(20, 20),
        bbox=(10, 15, 30, 25),
        pixel_count=40,
        score=100.0,
    )

    tracking_box = tracking_box_for_candidate(candidate, frame_shape=(80, 100))

    assert tracking_box == (0, 0, 60, 60)
