from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOANGLER_INTEGRATION") != "1",
    reason="Set AUTOANGLER_INTEGRATION=1 to run screen/GUI capability checks.",
)


def test_can_grab_screenshot() -> None:
    from PIL import ImageGrab

    img = ImageGrab.grab()
    assert img.size[0] > 0
    assert img.size[1] > 0


def test_can_create_tk_window() -> None:
    import tkinter as tk

    root = tk.Tk()
    try:
        root.update()
    finally:
        root.destroy()
