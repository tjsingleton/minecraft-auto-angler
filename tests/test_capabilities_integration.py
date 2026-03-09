from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOANGLER_INTEGRATION") != "1",
    reason="Set AUTOANGLER_INTEGRATION=1 to run screen/GUI capability checks.",
)


def test_can_grab_screenshot() -> None:
    from autoangler.capture_backend import create_capture_backend

    backend = create_capture_backend()
    try:
        img = backend.grab()
    finally:
        backend.close()
    assert img.shape[1] > 0
    assert img.shape[0] > 0


def test_can_create_tk_window() -> None:
    import tkinter as tk

    root = tk.Tk()
    try:
        root.update()
    finally:
        root.destroy()
