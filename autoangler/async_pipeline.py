from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import SimpleQueue
from time import monotonic
from typing import Callable, Literal

import cv2
import numpy as np

from autoangler.capture_backend import create_capture_backend
from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_image import CursorImage
from autoangler.line_detector import FishingLineDetector, LineCandidate, centered_tracking_box
from autoangler.logging_utils import build_session_video_path
from autoangler.minecraft_window import WindowInfo
from autoangler.pause_menu_detector import PauseMenuDetector
from autoangler.rod_detector import RodDetector
from autoangler.roi import cursor_anchor_in_roi, window_relative_box
from autoangler.session_recorder import SessionRecorder

GUIDE_STROKE_PX = 2


@dataclass(frozen=True)
class VisionRequest:
    epoch: int
    seq: int
    submitted_at: float
    minecraft_window: WindowInfo | None
    fishing_roi: tuple[int, int, int, int] | None
    tracking_box: tuple[int, int, int, int] | None
    detection_box: tuple[int, int, int, int] | None
    is_fishing: bool
    is_line_out: bool
    mode: Literal["idle_preview", "fishing"]


@dataclass(frozen=True)
class VisionResult:
    epoch: int
    seq: int
    submitted_at: float
    completed_at: float
    window_frame: np.ndarray
    main_preview_frame: np.ndarray
    tracking_preview: CursorImage
    debug_composite: np.ndarray
    preview_state: Literal["neutral", "valid", "invalid", "paused"]
    blocking_ui: Literal["none", "pause_menu"]
    rod_in_hand: bool
    line_candidate: LineCandidate | None
    line_pixels: int
    suggested_tracking_box: tuple[int, int, int, int] | None
    suggested_detection_box: tuple[int, int, int, int] | None
    capture_ms: float
    detect_ms: float
    annotate_ms: float
    capture_error: str | None


@dataclass(frozen=True)
class RecordingCommand:
    kind: Literal["frame", "screenshot", "mark", "close"]
    now: float | None = None
    path: Path | None = None
    label: str = ""
    raw_window_frame: np.ndarray | None = None
    debug_frame: np.ndarray | None = None
    image: np.ndarray | None = None


@dataclass(frozen=True)
class RecordingEvent:
    kind: Literal["screenshot_saved", "mark_saved", "drop_notice", "closed"]
    path: Path | None = None
    dropped_frames: int = 0
    queue_depth: int = 0


class RecordingWorker:
    def __init__(
        self,
        *,
        log_path: Path | None,
        queue_capacity: int = 32,
        recorder_factory: Callable[[Path], SessionRecorder] = SessionRecorder,
    ) -> None:
        self._log_path = Path(log_path) if log_path is not None else None
        self._queue_capacity = max(1, queue_capacity)
        self._recorder_factory = recorder_factory
        self._commands: deque[RecordingCommand] = deque()
        self._events: SimpleQueue[RecordingEvent] = SimpleQueue()
        self._condition = threading.Condition()
        self._closed = False
        self._close_requested = False
        self._dropped_frames = 0
        self._recorder: SessionRecorder | None = None
        self._window_video_path = (
            build_session_video_path(self._log_path, "window")
            if self._log_path is not None
            else None
        )
        self._debug_video_path = (
            build_session_video_path(self._log_path, "debug")
            if self._log_path is not None
            else None
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    @property
    def queue_depth(self) -> int:
        with self._condition:
            return len(self._commands)

    @property
    def window_video_path(self) -> Path | None:
        return self._window_video_path

    @property
    def debug_video_path(self) -> Path | None:
        return self._debug_video_path

    def enqueue_frame(
        self,
        *,
        now: float,
        raw_window_frame: np.ndarray,
        debug_frame: np.ndarray,
    ) -> None:
        self._enqueue(
            RecordingCommand(
                kind="frame",
                now=now,
                raw_window_frame=raw_window_frame.copy(),
                debug_frame=debug_frame.copy(),
            )
        )

    def enqueue_screenshot(self, *, path: Path, image: np.ndarray) -> None:
        self._enqueue(
            RecordingCommand(
                kind="screenshot",
                path=Path(path),
                image=image.copy(),
            )
        )

    def enqueue_mark(self, *, label: str, now: float) -> None:
        self._enqueue(RecordingCommand(kind="mark", label=label, now=now))

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            if not self._close_requested:
                self._close_requested = True
                self._enqueue_locked(RecordingCommand(kind="close"))
            self._condition.notify_all()
        self._thread.join(timeout=5)
        self._closed = True

    def poll_events(self) -> list[RecordingEvent]:
        events: list[RecordingEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Exception:
                return events

    def _enqueue(self, command: RecordingCommand) -> None:
        with self._condition:
            if self._close_requested and command.kind != "close":
                return
            self._enqueue_locked(command)
            self._condition.notify_all()

    def _enqueue_locked(self, command: RecordingCommand) -> None:
        if command.kind == "close":
            self._commands.append(command)
            return
        if len(self._commands) >= self._queue_capacity:
            dropped = self._drop_oldest_frame_locked()
            if dropped:
                self._dropped_frames += 1
                self._events.put(
                    RecordingEvent(
                        kind="drop_notice",
                        dropped_frames=1,
                        queue_depth=len(self._commands),
                    )
                )
        self._commands.append(command)

    def _drop_oldest_frame_locked(self) -> bool:
        for index, command in enumerate(self._commands):
            if command.kind == "frame":
                del self._commands[index]
                return True
        return False

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._commands:
                    self._condition.wait()
                command = self._commands.popleft()

            if command.kind == "close":
                recorder = self._recorder
                if recorder is not None:
                    recorder.close()
                    self._recorder = None
                self._events.put(RecordingEvent(kind="closed", queue_depth=self.queue_depth))
                return

            if command.kind == "frame":
                recorder = self._ensure_recorder()
                if recorder is not None and command.now is not None:
                    recorder.record_frame(
                        now=command.now,
                        raw_window_frame=command.raw_window_frame,
                        debug_frame=command.debug_frame,
                    )
                continue

            if (
                command.kind == "screenshot"
                and command.path is not None
                and command.image is not None
            ):
                _save_image(command.path, command.image)
                self._events.put(
                    RecordingEvent(
                        kind="screenshot_saved",
                        path=command.path,
                        queue_depth=self.queue_depth,
                    )
                )
                continue

            if command.kind == "mark" and command.now is not None:
                recorder = self._ensure_recorder()
                if recorder is None:
                    continue
                clip_path = recorder.mark(command.label, now=command.now)
                self._events.put(
                    RecordingEvent(
                        kind="mark_saved",
                        path=clip_path,
                        queue_depth=self.queue_depth,
                    )
                )

    def _ensure_recorder(self) -> SessionRecorder | None:
        if self._recorder is not None:
            return self._recorder
        if self._log_path is None:
            return None
        self._recorder = self._recorder_factory(self._log_path)
        return self._recorder


class VisionWorker:
    def __init__(
        self,
        *,
        processor: Callable[[VisionRequest], VisionResult] | None = None,
    ) -> None:
        self._processor = processor or VisionProcessor()
        self._condition = threading.Condition()
        self._pending: VisionRequest | None = None
        self._results: SimpleQueue[VisionResult] = SimpleQueue()
        self._closed = False
        self._close_requested = False
        self._dropped_frames = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def dropped_frames(self) -> int:
        return self._dropped_frames

    def submit(self, request: VisionRequest) -> None:
        with self._condition:
            if self._close_requested:
                return
            if self._pending is not None:
                self._dropped_frames += 1
            self._pending = request
            self._condition.notify_all()

    def poll_results(self) -> list[VisionResult]:
        results: list[VisionResult] = []
        while True:
            try:
                results.append(self._results.get_nowait())
            except Exception:
                return results

    def close(self) -> None:
        with self._condition:
            self._close_requested = True
            self._condition.notify_all()
        self._thread.join(timeout=5)
        self._closed = True

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._close_requested:
                    self._condition.wait()
                if self._pending is None and self._close_requested:
                    return
                request = self._pending
                self._pending = None

            if request is None:
                continue
            result = self._processor(request)
            self._results.put(result)


class VisionProcessor:
    def __init__(self) -> None:
        capture_backend = create_capture_backend()
        self._camera = CursorCamera(magnification=10, capture_backend=capture_backend)
        self._line_detector = FishingLineDetector()
        self._pause_menu_detector = PauseMenuDetector()
        self._rod_detector = RodDetector()

    def __call__(self, request: VisionRequest) -> VisionResult:
        blank = self._camera.blank()
        empty_debug = _build_debug_composite(
            blank.original,
            blank.computer,
            status_lines=["status:waiting", "track:None detect:None", "line_px:0"],
        )
        if request.minecraft_window is None or request.fishing_roi is None:
            preview_state: Literal["neutral", "valid", "invalid", "paused"] = (
                "neutral" if request.mode == "idle_preview" else "invalid"
            )
            return VisionResult(
                epoch=request.epoch,
                seq=request.seq,
                submitted_at=request.submitted_at,
                completed_at=monotonic(),
                window_frame=blank.original,
                main_preview_frame=blank.original,
                tracking_preview=blank,
                debug_composite=empty_debug,
                preview_state=preview_state,
                blocking_ui="none",
                rod_in_hand=False,
                line_candidate=None,
                line_pixels=0,
                suggested_tracking_box=None,
                suggested_detection_box=None,
                capture_ms=0.0,
                detect_ms=0.0,
                annotate_ms=0.0,
                capture_error=None,
            )

        capture_start = monotonic()
        try:
            window = request.minecraft_window
            bbox = (
                window.left,
                window.top,
                window.left + window.width,
                window.top + window.height,
            )
            window_image = self._camera.capture_bbox(bbox, magnify=False)
        except Exception as exc:
            return VisionResult(
                epoch=request.epoch,
                seq=request.seq,
                submitted_at=request.submitted_at,
                completed_at=monotonic(),
                window_frame=blank.original,
                main_preview_frame=blank.original,
                tracking_preview=blank,
                debug_composite=empty_debug,
                preview_state="invalid",
                blocking_ui="none",
                rod_in_hand=False,
                line_candidate=None,
                line_pixels=0,
                suggested_tracking_box=None,
                suggested_detection_box=None,
                capture_ms=round((monotonic() - capture_start) * 1000, 1),
                detect_ms=0.0,
                annotate_ms=0.0,
                capture_error=str(exc),
            )

        capture_ms = round((monotonic() - capture_start) * 1000, 1)
        window_frame = window_image.original
        roi_box, roi_frame = _window_frame_and_roi(
            window_frame,
            request.fishing_roi,
            request.minecraft_window,
        )
        tracking_box = request.tracking_box or _default_tracking_box(
            roi_frame.shape,
            minecraft_window=request.minecraft_window,
            fishing_roi=request.fishing_roi,
        )
        detection_box = request.detection_box or _default_detection_box(
            roi_frame.shape,
            minecraft_window=request.minecraft_window,
            fishing_roi=request.fishing_roi,
        )
        suggested_tracking_box = tracking_box if request.tracking_box is None else None
        suggested_detection_box = detection_box if request.detection_box is None else None

        detect_start = monotonic()
        if request.mode == "idle_preview":
            rod_in_hand = False
            line_candidate = None
            processed_tracking = _crop_box(roi_frame, detection_box).copy()
            line_pixels = 0
            preview_state: Literal["neutral", "valid", "invalid", "paused"] = "neutral"
            blocking_ui: Literal["none", "pause_menu"] = "none"
            status_lines = [
                "mode:idle_preview",
                f"track:{tracking_box} detect:{detection_box}",
                "candidate:-",
            ]
        elif self._pause_menu_detector.detect(window_frame):
            rod_in_hand = False
            line_candidate = None
            processed_tracking = _crop_box(roi_frame, detection_box).copy()
            line_pixels = 0
            preview_state = "paused"
            blocking_ui = "pause_menu"
            status_lines = [
                "mode:paused menu:pause",
                f"track:{tracking_box} detect:{detection_box}",
                "candidate:-",
            ]
        else:
            rod_in_hand = self._rod_detector.detect(window_frame, window=request.minecraft_window)
            line_candidate = self._line_detector.find_line(roi_frame)
            processed_tracking = self._line_detector.threshold_dark_pixels(
                _crop_box(roi_frame, detection_box)
            )
            line_pixels = int(np.sum(processed_tracking == 0))
            preview_valid = (line_pixels > 0) if request.is_line_out else rod_in_hand
            preview_state = "valid" if preview_valid else "invalid"
            blocking_ui = "none"
            status_lines = [
                f"rod:{int(rod_in_hand)} line_px:{line_pixels}",
                f"track:{tracking_box} detect:{detection_box}",
                f"candidate:{'-' if line_candidate is None else line_candidate.center}",
            ]
        detect_ms = round((monotonic() - detect_start) * 1000, 1)

        annotate_start = monotonic()
        tracking_preview = _build_tracking_preview(
            window_frame,
            roi_box,
            roi_frame,
            tracking_box=tracking_box,
            detection_box=detection_box,
            line_candidate=line_candidate,
            processed_tracking=processed_tracking,
            line_pixels=line_pixels,
        )
        main_preview_frame = _build_main_preview_frame(
            roi_frame,
            tracking_box=tracking_box,
            detection_box=detection_box,
            line_candidate=line_candidate,
            preview_state=preview_state,
        )
        debug_composite = _build_debug_composite(
            tracking_preview.original,
            tracking_preview.computer,
            status_lines=status_lines,
        )
        annotate_ms = round((monotonic() - annotate_start) * 1000, 1)

        return VisionResult(
            epoch=request.epoch,
            seq=request.seq,
            submitted_at=request.submitted_at,
            completed_at=monotonic(),
            window_frame=window_frame.copy(),
            main_preview_frame=main_preview_frame,
            tracking_preview=tracking_preview,
            debug_composite=debug_composite,
            preview_state=preview_state,
            blocking_ui=blocking_ui,
            rod_in_hand=rod_in_hand,
            line_candidate=line_candidate,
            line_pixels=line_pixels,
            suggested_tracking_box=suggested_tracking_box,
            suggested_detection_box=suggested_detection_box,
            capture_ms=capture_ms,
            detect_ms=detect_ms,
            annotate_ms=annotate_ms,
            capture_error=None,
        )


def _save_image(path: Path, image: np.ndarray) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    array = image.astype("uint8")
    if array.ndim == 3:
        Image.fromarray(array).save(path)
    else:
        Image.fromarray(array, mode="L").save(path)


def _window_frame_and_roi(
    window_frame: np.ndarray,
    fishing_roi: tuple[int, int, int, int],
    minecraft_window: WindowInfo,
) -> tuple[tuple[int, int, int, int], np.ndarray]:
    roi_box = window_relative_box(fishing_roi, minecraft_window)
    x1, y1, x2, y2 = roi_box
    return roi_box, window_frame[y1:y2, x1:x2]


def _crop_box(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = box
    return frame[y1:y2, x1:x2]


def _default_tracking_box(
    frame_shape: tuple[int, ...],
    *,
    minecraft_window: WindowInfo | None,
    fishing_roi: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    if minecraft_window is not None and fishing_roi is not None:
        anchor = cursor_anchor_in_roi(minecraft_window, fishing_roi)
        return centered_tracking_box(frame_shape, center=anchor)
    return centered_tracking_box(frame_shape)


def _default_detection_box(
    frame_shape: tuple[int, ...],
    *,
    minecraft_window: WindowInfo | None,
    fishing_roi: tuple[int, int, int, int] | None,
) -> tuple[int, int, int, int]:
    frame_height, frame_width = frame_shape[:2]
    if minecraft_window is not None and fishing_roi is not None:
        anchor_x, anchor_y = cursor_anchor_in_roi(minecraft_window, fishing_roi)
    else:
        anchor_x, anchor_y = frame_width // 2, frame_height // 2

    width = 44
    height = 36
    left = anchor_x - (width // 2)
    top = anchor_y + 8
    return _clamp_box(frame_shape, left=left, top=top, width=width, height=height)


def _clamp_box(
    frame_shape: tuple[int, ...], *, left: int, top: int, width: int, height: int
) -> tuple[int, int, int, int]:
    frame_height, frame_width = frame_shape[:2]
    right = left + width
    bottom = top + height

    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > frame_width:
        left -= right - frame_width
        right = frame_width
    if bottom > frame_height:
        top -= bottom - frame_height
        bottom = frame_height

    left = max(0, left)
    top = max(0, top)
    right = min(frame_width, right)
    bottom = min(frame_height, bottom)
    return int(left), int(top), int(right), int(bottom)


def _build_tracking_preview(
    window_frame: np.ndarray,
    roi_box: tuple[int, int, int, int],
    roi_frame: np.ndarray,
    *,
    tracking_box: tuple[int, int, int, int],
    detection_box: tuple[int, int, int, int],
    line_candidate: LineCandidate | None,
    processed_tracking: np.ndarray,
    line_pixels: int,
) -> CursorImage:
    annotated = window_frame.copy()
    roi_left, roi_top, roi_right, roi_bottom = roi_box
    cv2.rectangle(
        annotated,
        (roi_left, roi_top),
        (roi_right, roi_bottom),
        color=160,
        thickness=GUIDE_STROKE_PX,
    )

    x1, y1, x2, y2 = tracking_box
    cv2.rectangle(
        annotated,
        (roi_left + x1, roi_top + y1),
        (roi_left + x2, roi_top + y2),
        color=0,
        thickness=GUIDE_STROKE_PX,
    )

    dx1, dy1, dx2, dy2 = detection_box
    cv2.rectangle(
        annotated,
        (roi_left + dx1, roi_top + dy1),
        (roi_left + dx2, roi_top + dy2),
        color=64,
        thickness=GUIDE_STROKE_PX,
    )

    if line_candidate is not None:
        lx1, ly1, lx2, ly2 = line_candidate.bbox
        cv2.rectangle(
            annotated,
            (roi_left + lx1, roi_top + ly1),
            (roi_left + lx2, roi_top + ly2),
            color=96,
            thickness=1,
        )
        cv2.circle(
            annotated,
            (roi_left + line_candidate.center[0], roi_top + line_candidate.center[1]),
            radius=2,
            color=96,
            thickness=-1,
        )

    return CursorImage(
        original=annotated,
        computer=processed_tracking,
        black_pixel_count=line_pixels,
    )


def _build_main_preview_frame(
    roi_frame: np.ndarray,
    *,
    tracking_box: tuple[int, int, int, int],
    detection_box: tuple[int, int, int, int],
    line_candidate: LineCandidate | None,
    preview_state: Literal["neutral", "valid", "invalid", "paused"],
) -> np.ndarray:
    annotated = roi_frame.copy()
    x1, y1, x2, y2 = tracking_box
    cv2.rectangle(annotated, (x1, y1), (x2, y2), color=0, thickness=GUIDE_STROKE_PX)

    dx1, dy1, dx2, dy2 = detection_box
    cv2.rectangle(annotated, (dx1, dy1), (dx2, dy2), color=64, thickness=GUIDE_STROKE_PX)

    if line_candidate is not None:
        lx1, ly1, lx2, ly2 = line_candidate.bbox
        cv2.rectangle(annotated, (lx1, ly1), (lx2, ly2), color=96, thickness=1)
        cv2.circle(annotated, line_candidate.center, radius=2, color=96, thickness=-1)

    if preview_state == "neutral":
        border_color = 128
    elif preview_state == "valid":
        border_color = 96
    elif preview_state == "paused":
        border_color = 48
    else:
        border_color = 0
    height, width = annotated.shape[:2]
    cv2.rectangle(annotated, (0, 0), (width - 1, height - 1), color=border_color, thickness=2)
    return annotated


def _build_debug_composite(
    original: np.ndarray,
    processed: np.ndarray,
    *,
    status_lines: list[str],
) -> np.ndarray:
    left = _to_bgr(original)
    right = _to_bgr(processed)

    max_mask_scale = max(1, left.shape[0] // max(right.shape[0], 1))
    mask_scale = max(1, min(8, max_mask_scale))
    right = cv2.resize(
        right,
        (right.shape[1] * mask_scale, right.shape[0] * mask_scale),
        interpolation=cv2.INTER_NEAREST,
    )

    gap = 16
    line_height = 22
    text_height = (line_height * len(status_lines)) + 16
    panel_width = max(right.shape[1], 360)
    canvas_height = max(left.shape[0], right.shape[0] + gap + text_height)
    canvas_width = left.shape[1] + gap + panel_width
    canvas = np.full((canvas_height, canvas_width, 3), 24, dtype=np.uint8)

    canvas[: left.shape[0], : left.shape[1]] = left
    right_left = left.shape[1] + gap
    canvas[: right.shape[0], right_left : right_left + right.shape[1]] = right

    text_y = right.shape[0] + gap + 18
    for line in status_lines:
        cv2.putText(
            canvas,
            line,
            (right_left, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )
        text_y += line_height

    return canvas


def _to_bgr(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    return frame
