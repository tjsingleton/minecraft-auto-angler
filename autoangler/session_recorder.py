from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from autoangler.logging_utils import build_session_mark_dir, build_session_video_path

logger = logging.getLogger(__name__)


@dataclass
class _RecordedFrame:
    raw_window_frame: np.ndarray
    debug_frame: np.ndarray


@dataclass
class _PendingClip:
    path: Path
    frames: list[_RecordedFrame]
    remaining_post_frames: int


class SessionRecorder:
    def __init__(
        self,
        log_path: Path,
        *,
        fps: float = 30.0,
        pre_frames: int = 18,
        post_frames: int = 18,
    ) -> None:
        self._log_path = Path(log_path)
        self._fps = fps
        self._pre_frames = max(1, pre_frames)
        self._post_frames = max(0, post_frames)
        self._buffer: deque[_RecordedFrame] = deque(maxlen=self._pre_frames)
        self._pending: list[_PendingClip] = []
        self._mark_index = 0

        self.window_video_path = build_session_video_path(self._log_path, "window")
        self.debug_video_path = build_session_video_path(self._log_path, "debug")

        self._window_writer = None
        self._debug_writer = None
        self._window_size: tuple[int, int] | None = None
        self._debug_size: tuple[int, int] | None = None

    def record_frame(
        self,
        *,
        now: float,
        raw_window_frame: np.ndarray,
        debug_frame: np.ndarray,
    ) -> None:
        del now
        frame = _RecordedFrame(
            raw_window_frame=raw_window_frame.copy(),
            debug_frame=debug_frame.copy(),
        )
        self._buffer.append(frame)

        self._write_window_frame(frame.raw_window_frame)
        self._write_debug_frame(frame.debug_frame)
        self._update_pending_clips(frame)

    def mark(self, label: str, *, now: float) -> Path:
        del now
        clip_path = build_session_mark_dir(self._log_path, label, self._mark_index)
        self._mark_index += 1

        pending = _PendingClip(
            path=clip_path,
            frames=[
                _RecordedFrame(
                    raw_window_frame=frame.raw_window_frame.copy(),
                    debug_frame=frame.debug_frame.copy(),
                )
                for frame in self._buffer
            ],
            remaining_post_frames=self._post_frames,
        )
        if pending.remaining_post_frames <= 0:
            self._flush_clip(pending)
            return clip_path

        self._pending.append(pending)
        return clip_path

    def finish_clips(self) -> None:
        for pending in list(self._pending):
            self._flush_clip(pending)

    def close(self) -> None:
        self.finish_clips()
        self._release_writer("_window_writer")
        self._release_writer("_debug_writer")
        self._buffer.clear()
        self._pending.clear()
        self._window_size = None
        self._debug_size = None

    def _write_window_frame(self, frame: np.ndarray) -> None:
        writer = self._ensure_writer(
            attr_name="_window_writer",
            path=self.window_video_path,
            size_attr="_window_size",
            frame=frame,
        )
        writer.write(self._normalize_video_frame(frame, self._window_size))

    def _write_debug_frame(self, frame: np.ndarray) -> None:
        writer = self._ensure_writer(
            attr_name="_debug_writer",
            path=self.debug_video_path,
            size_attr="_debug_size",
            frame=frame,
        )
        writer.write(self._normalize_video_frame(frame, self._debug_size))

    def _ensure_writer(
        self,
        *,
        attr_name: str,
        path: Path,
        size_attr: str,
        frame: np.ndarray,
    ):
        writer = getattr(self, attr_name)
        if writer is not None:
            return writer

        size = (int(frame.shape[1]), int(frame.shape[0]))
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            self._fps,
            size,
        )
        setattr(self, attr_name, writer)
        setattr(self, size_attr, size)
        logger.info("Recording video to %s", path)
        return writer

    @staticmethod
    def _normalize_video_frame(
        frame: np.ndarray, size: tuple[int, int] | None
    ) -> np.ndarray:
        if size is None:
            target = frame
        else:
            target = frame
            if (frame.shape[1], frame.shape[0]) != size:
                target = cv2.resize(frame, size, interpolation=cv2.INTER_NEAREST)

        if target.ndim == 2:
            return cv2.cvtColor(target, cv2.COLOR_GRAY2BGR)
        return target

    def _update_pending_clips(self, frame: _RecordedFrame) -> None:
        for pending in list(self._pending):
            if pending.remaining_post_frames > 0:
                pending.frames.append(
                    _RecordedFrame(
                        raw_window_frame=frame.raw_window_frame.copy(),
                        debug_frame=frame.debug_frame.copy(),
                    )
                )
                pending.remaining_post_frames -= 1

            if pending.remaining_post_frames <= 0:
                self._flush_clip(pending)

    def _flush_clip(self, pending: _PendingClip) -> None:
        pending.path.mkdir(parents=True, exist_ok=True)
        for index, frame in enumerate(pending.frames):
            self._save_png(pending.path / f"frame-{index:03d}-window.png", frame.raw_window_frame)
            self._save_png(pending.path / f"frame-{index:03d}-debug.png", frame.debug_frame)
        if pending in self._pending:
            self._pending.remove(pending)
        logger.info("Saved mark clip to %s", pending.path)

    @staticmethod
    def _save_png(path: Path, frame: np.ndarray) -> None:
        array = frame.astype("uint8")
        if array.ndim == 3:
            Image.fromarray(array).save(path)
        else:
            Image.fromarray(array, mode="L").save(path)

    def _release_writer(self, attr_name: str) -> None:
        writer = getattr(self, attr_name)
        if writer is None:
            return
        writer.release()
        setattr(self, attr_name, None)
