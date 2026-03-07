from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

import numpy as np
from PIL import Image, ImageTk

from autoangler.cursor_image import CursorImage


@dataclass(frozen=True)
class ImageViewerTkElements:
    frame: ttk.Frame
    original_label: tk.Label
    computer_label: tk.Label


class ImageViewerTk:
    def __init__(self) -> None:
        self._photo_left: ImageTk.PhotoImage | None = None
        self._photo_right: ImageTk.PhotoImage | None = None
        self._elements: ImageViewerTkElements | None = None

    def frame(self, parent) -> ttk.Frame:
        if self._elements is not None:
            return self._elements.frame

        frame = ttk.Frame(parent)
        original_label = tk.Label(frame)
        computer_label = tk.Label(frame)

        original_label.grid(row=0, column=0, padx=(0, 8), pady=8)
        computer_label.grid(row=0, column=1, padx=(0, 0), pady=8)

        self._elements = ImageViewerTkElements(
            frame=frame,
            original_label=original_label,
            computer_label=computer_label,
        )
        return frame

    def update(self, image: CursorImage) -> None:
        if self._elements is None:
            raise RuntimeError("Call frame(parent) before update().")

        self._photo_left = self._as_photo(image.original)
        self._photo_right = self._as_photo(image.computer)

        self._elements.original_label.configure(image=self._photo_left)
        self._elements.computer_label.configure(image=self._photo_right)
        self._elements.original_label.image = self._photo_left
        self._elements.computer_label.image = self._photo_right

    @staticmethod
    def _as_photo(array: np.ndarray) -> ImageTk.PhotoImage:
        pil = Image.fromarray(array.astype("uint8"), mode="L")
        return ImageTk.PhotoImage(pil)
