from __future__ import annotations

from pathlib import Path

import cv2

from autoangler.pause_menu_detector import PauseMenuDetector


def test_detector_matches_pause_menu_fixture() -> None:
    detector = PauseMenuDetector()

    assert detector.detect(_fixture_path("pause-menu-open.png")) is True


def test_detector_ignores_normal_gameplay_fixture() -> None:
    detector = PauseMenuDetector()

    assert detector.detect(_fixture_path("gameplay.png")) is False


def _fixture_path(name: str):
    frame = cv2.imread(str(Path(__file__).parent / "fixtures" / "pause_menu" / name))
    assert frame is not None
    return frame
