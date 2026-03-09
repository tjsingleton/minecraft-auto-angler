from __future__ import annotations


class LineWatcher:
    def __init__(
        self,
        *,
        drop_ratio: float = 0.4,
        min_frames: int = 2,
        min_reference_pixels: int = 20,
        min_trigger_pixels: int = 4,
    ) -> None:
        self._drop_ratio = drop_ratio
        self._min_frames = min_frames
        self._min_reference_pixels = min_reference_pixels
        self._min_trigger_pixels = min_trigger_pixels
        self._max_reference_jump_ratio = 2.0
        self.reset()

    @property
    def reference_pixels(self) -> int:
        return self._reference_pixels

    @property
    def trigger_pixels(self) -> int:
        return self._trigger_pixels

    @property
    def weak_frames(self) -> int:
        return self._weak_frames

    @property
    def min_frames(self) -> int:
        return self._min_frames

    def reset(self) -> None:
        self._reference_pixels = 0
        self._trigger_pixels = 0
        self._weak_frames = 0

    def observe(self, pixel_count: int, *, active: bool) -> bool:
        if not active:
            self.reset()
            return False

        if self._reference_pixels == 0:
            self._reference_pixels = pixel_count
        elif pixel_count > self._reference_pixels:
            max_allowed = max(
                self._min_reference_pixels,
                int(self._reference_pixels * self._max_reference_jump_ratio),
            )
            if pixel_count <= max_allowed:
                self._reference_pixels = pixel_count
        self._trigger_pixels = max(
            self._min_trigger_pixels,
            int(self._reference_pixels * self._drop_ratio),
        )

        if self._reference_pixels < self._min_reference_pixels:
            return False

        if pixel_count == 0:
            self._weak_frames = max(self._weak_frames, self._min_frames)
            return True

        if pixel_count <= self._trigger_pixels:
            self._weak_frames += 1
        else:
            self._weak_frames = 0

        return self._weak_frames >= self._min_frames
