from __future__ import annotations

import os
from typing import Protocol

import numpy as np
from PIL import ImageGrab

CaptureBBox = tuple[int, int, int, int]


class CaptureBackend(Protocol):
    backend_name: str

    def grab(self, bbox: CaptureBBox | None = None) -> np.ndarray: ...

    def close(self) -> None: ...


class PillowCaptureBackend:
    backend_name = "pil"

    def grab(self, bbox: CaptureBBox | None = None) -> np.ndarray:
        image = ImageGrab.grab(bbox=bbox)
        return _normalize_to_rgb(np.array(image))

    def close(self) -> None:
        return None


class MSSCaptureBackend:
    backend_name = "mss"

    def __init__(self) -> None:
        import mss

        self._mss = mss.mss()

    def grab(self, bbox: CaptureBBox | None = None) -> np.ndarray:
        if bbox is None:
            monitor = self._mss.monitors[0]
        else:
            left, top, right, bottom = bbox
            monitor = {
                "left": int(left),
                "top": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
            }

        shot = self._mss.grab(monitor)
        frame = np.asarray(shot, dtype=np.uint8)
        if frame.ndim == 3 and frame.shape[2] == 4:
            return frame[:, :, [2, 1, 0]].copy()
        return _normalize_to_rgb(frame)

    def close(self) -> None:
        self._mss.close()


def create_capture_backend() -> CaptureBackend:
    backend_name = os.environ.get("AUTOANGLER_CAPTURE_BACKEND", "mss").strip().lower()
    if backend_name in {"", "mss"}:
        return MSSCaptureBackend()
    if backend_name == "pil":
        return PillowCaptureBackend()
    raise ValueError(f"Unsupported capture backend: {backend_name}")


def _normalize_to_rgb(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return np.repeat(frame[:, :, None], 3, axis=2).astype(np.uint8, copy=False)
    if frame.ndim == 3 and frame.shape[2] == 4:
        return frame[:, :, :3].astype(np.uint8, copy=False)
    return frame.astype(np.uint8, copy=False)
