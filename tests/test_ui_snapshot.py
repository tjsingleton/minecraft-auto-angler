from __future__ import annotations

from pathlib import Path

from PIL import Image

from autoangler.ui_snapshot import capture_ui_screenshot


def test_capture_ui_screenshot_writes_png(tmp_path: Path) -> None:
    calls: list[tuple[int, int, int, int]] = []

    def fake_grab(bbox: tuple[int, int, int, int]) -> Image.Image:
        calls.append(bbox)
        width = max(1, bbox[2] - bbox[0])
        height = max(1, bbox[3] - bbox[1])
        return Image.new("RGB", (width, height), "black")

    output_path = capture_ui_screenshot(tmp_path / "ui-snapshot.png", grab_image=fake_grab)

    assert output_path == tmp_path / "ui-snapshot.png"
    assert output_path.exists()
    assert calls
    assert calls[0][2] > calls[0][0]
    assert calls[0][3] > calls[0][1]
