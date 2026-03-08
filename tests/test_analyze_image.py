from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from autoangler.analyze_image import analyze_frame, main


def _synthetic_frame() -> np.ndarray:
    frame = np.full((120, 120), 180, dtype=np.uint8)
    cv2.line(frame, (50, 40), (70, 80), color=0, thickness=2)
    return frame


def test_analyze_frame_uses_center_box_by_default() -> None:
    analysis = analyze_frame(_synthetic_frame(), tracking_box=None, tracking_box_size=80)

    assert analysis.tracking_box == (20, 20, 100, 100)
    assert analysis.line_pixels > 0
    assert analysis.candidate is not None


def test_main_writes_analysis_files(tmp_path: Path, capsys) -> None:
    image_path = tmp_path / "frame.png"
    output_dir = tmp_path / "analysis"
    cv2.imwrite(str(image_path), _synthetic_frame())

    exit_code = main([str(image_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "frame-analysis-crop.png").exists()
    assert (output_dir / "frame-analysis-mask.png").exists()
    assert (output_dir / "frame-analysis-overlay.png").exists()

    summary = json.loads((output_dir / "frame-analysis.json").read_text())
    assert summary["tracking_box"] == [20, 20, 100, 100]
    assert summary["line_pixels"] > 0
    assert summary["candidate_bbox"] is not None

    stdout = capsys.readouterr().out
    assert "frame-analysis.json" in stdout
