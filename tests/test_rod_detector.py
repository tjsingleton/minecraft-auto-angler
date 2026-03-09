from __future__ import annotations

from importlib import resources

import cv2
import numpy as np

from autoangler.minecraft_window import WindowInfo
from autoangler.rod_detector import RodDetector, selected_slot_box


def test_selected_slot_box_stays_inside_window() -> None:
    window = WindowInfo(title="Minecraft", left=10, top=20, width=1280, height=720)

    box = selected_slot_box(window)

    left, top, right, bottom = box
    assert window.left <= left < right <= window.left + window.width
    assert window.top <= top < bottom <= window.top + window.height


def test_detector_finds_template_in_selected_slot() -> None:
    window = WindowInfo(title="Minecraft", left=0, top=0, width=1280, height=720)
    detector = RodDetector()
    template_path = resources.files("autoangler.assets").joinpath("fishing_rod_slot_template.png")
    template = cv2.imread(str(template_path))
    assert template is not None

    frame = np.zeros((window.height, window.width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = selected_slot_box(window)
    slot = frame[y1:y2, x1:x2]
    top = max(0, (slot.shape[0] - template.shape[0]) // 2)
    left = max(0, (slot.shape[1] - template.shape[1]) // 2)
    slot[top : top + template.shape[0], left : left + template.shape[1]] = template

    assert detector.detect(frame, window=window) is True


def test_detector_rejects_empty_slot() -> None:
    window = WindowInfo(title="Minecraft", left=0, top=0, width=1280, height=720)
    detector = RodDetector()
    frame = np.zeros((window.height, window.width, 3), dtype=np.uint8)

    assert detector.detect(frame, window=window) is False
