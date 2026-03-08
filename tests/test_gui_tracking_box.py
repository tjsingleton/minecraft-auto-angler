from __future__ import annotations

import numpy as np

from autoangler.gui_tk import AutoFishTkApp
from autoangler.line_detector import LineCandidate
from autoangler.minecraft_window import WindowInfo


def test_calibrated_tracking_box_prefers_cursor_anchor_over_detected_line(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._minecraft_window = WindowInfo(
        title="Minecraft",
        left=18,
        top=30,
        width=1280,
        height=705,
        owner="java",
    )
    app._fishing_roi = (338, 147, 978, 500)
    frame = np.full((353, 640), 255, dtype=np.uint8)
    candidate = LineCandidate(
        center=(40, 40),
        bbox=(20, 20, 60, 60),
        pixel_count=80,
        score=100.0,
    )
    monkeypatch.setattr(app._line_detector, "find_line", lambda _frame: candidate)

    tracking_box = app._calibrated_tracking_box(frame)

    assert tracking_box == (280, 210, 360, 290)


def test_default_detection_box_is_smaller_and_left_biased_below_cursor_anchor() -> None:
    app = AutoFishTkApp()
    app._minecraft_window = WindowInfo(
        title="Minecraft",
        left=18,
        top=30,
        width=1280,
        height=705,
        owner="java",
    )
    app._fishing_roi = (338, 147, 978, 500)
    frame = np.full((353, 640), 255, dtype=np.uint8)

    detection_box = app._default_detection_box(frame)

    assert detection_box == (296, 258, 340, 294)


def test_build_tracking_preview_scores_detection_box_not_tracking_box() -> None:
    app = AutoFishTkApp()
    app._tracking_box = (280, 210, 360, 290)
    app._detection_box = (296, 258, 340, 294)
    window_frame = np.full((400, 700), 255, dtype=np.uint8)
    roi_box = (10, 20, 650, 373)
    roi_frame = window_frame[20:373, 10:650]

    preview = app._build_tracking_preview(window_frame, roi_box, roi_frame)

    assert preview.computer.shape == (36, 44)
