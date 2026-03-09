from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

PREVIEW_MAX_WIDTH = 360
PREVIEW_MAX_HEIGHT = 240


def fit_within(width: int, height: int, max_width: int, max_height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return max_width, max_height

    scale = min(max_width / width, max_height / height, 1.0)
    return max(1, int(width * scale)), max(1, int(height * scale))


@dataclass(frozen=True)
class ImageViewerTkElements:
    frame: ttk.Frame
    primary_label: tk.Label
    secondary_label: tk.Label | None


class ImageViewerTk:
    def __init__(self, *, dual: bool = True) -> None:
        self._dual = dual
        self._photo_left: ImageTk.PhotoImage | None = None
        self._photo_right: ImageTk.PhotoImage | None = None
        self._elements: ImageViewerTkElements | None = None

    def frame(self, parent) -> ttk.Frame:
        if self._elements is not None:
            return self._elements.frame

        frame = ttk.Frame(parent)
        primary_label = tk.Label(frame, highlightthickness=2)
        secondary_label = tk.Label(frame) if self._dual else None

        primary_label.grid(row=0, column=0, padx=(0, 8 if self._dual else 0), pady=8)
        if secondary_label is not None:
            secondary_label.grid(row=0, column=1, padx=(0, 0), pady=8)

        self._elements = ImageViewerTkElements(
            frame=frame,
            primary_label=primary_label,
            secondary_label=secondary_label,
        )
        return frame

    def update(self, image, secondary: np.ndarray | None = None) -> None:
        if self._elements is None:
            raise RuntimeError("Call frame(parent) before update().")

        primary = getattr(image, "original", image)
        secondary_image = getattr(image, "computer", secondary)

        self._photo_left = self._as_photo(primary)
        self._elements.primary_label.configure(image=self._photo_left)
        self._elements.primary_label.image = self._photo_left

        if self._elements.secondary_label is not None and secondary_image is not None:
            self._photo_right = self._as_photo(secondary_image)
            self._elements.secondary_label.configure(image=self._photo_right)
            self._elements.secondary_label.image = self._photo_right

    def set_border(self, color: str) -> None:
        if self._elements is None:
            return
        self._elements.primary_label.configure(highlightbackground=color, highlightcolor=color)

    @staticmethod
    def _as_photo(array: np.ndarray) -> ImageTk.PhotoImage:
        if array.ndim == 3:
            pil = Image.fromarray(array.astype("uint8"), mode="RGB")
        else:
            pil = Image.fromarray(array.astype("uint8"), mode="L")
        new_size = fit_within(pil.width, pil.height, PREVIEW_MAX_WIDTH, PREVIEW_MAX_HEIGHT)
        if new_size != pil.size:
            pil = pil.resize(new_size, Image.Resampling.NEAREST)
        return ImageTk.PhotoImage(pil)
