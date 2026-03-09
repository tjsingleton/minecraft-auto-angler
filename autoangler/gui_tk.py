from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from csv import DictWriter
from pathlib import Path
from time import monotonic, time
from typing import Any

import cv2
import numpy as np
import pyautogui
from pynput import keyboard

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from autoangler.capture_backend import create_capture_backend
from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_image import CursorImage
from autoangler.cursor_locator import CursorLocator
from autoangler.line_detector import (
    FishingLineDetector,
    LineCandidate,
    centered_tracking_box,
)
from autoangler.line_watcher import LineWatcher
from autoangler.logging_utils import (
    build_session_capture_path,
    build_session_profile_path,
    build_session_trace_path,
)
from autoangler.minecraft_window import WindowInfo, selected_minecraft_window
from autoangler.profiling import RollingProfiler, TickProfile
from autoangler.roi import (
    clamp_roi_to_window,
    cursor_anchor_in_roi,
    default_fishing_roi,
    window_relative_box,
)
from autoangler.screen import get_virtual_screen_bounds
from autoangler.session_recorder import SessionRecorder

# The default pause sometimes causes the cast to also retrieve
pyautogui.PAUSE = 0.01

MINECRAFT_TICKS_PER_MC_DAY = 24000
MINECRAFT_TICKS_PER_HOUR = MINECRAFT_TICKS_PER_MC_DAY / 24
MINECRAFT_IRL_MINUTES_PER_MC_DAY = 20
MINECRAFT_IRL_MINUTES_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_DAY / 24
MINECRAFT_IRL_SECONDS_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_HOUR * 60

logger = logging.getLogger(__name__)
DEFAULT_WINDOW_GEOMETRY = "860x440+300+0"


def hotkey_hint_text(hotkeys_enabled: bool) -> str:
    suffix = "" if hotkeys_enabled else " (global hotkeys disabled)"
    return (
        f"Hotkeys: M mark | F6 reel+mark | F7 record | F8 screenshot | F12 start | "
        f"F9 calibrate box | ESC stop | F10 exit{suffix}"
    )


def line_state_text(*, is_line_out: bool) -> str:
    return "Line: Out" if is_line_out else "Line: In"


def tracking_status_text(
    *,
    line_pixels: int,
    watcher: LineWatcher,
    is_line_out: bool,
    bite_detected: bool,
    elapsed_s: int,
    tick_interval: int,
    duration_ms: float,
    avg_ms: float,
) -> str:
    return (
        f"line {line_pixels} <= {watcher.trigger_pixels} "
        f"weak:{watcher.weak_frames}/{watcher.min_frames} "
        f"out:{int(is_line_out)} bite:{int(bite_detected)} "
        f"ref:{watcher.reference_pixels} "
        f"{elapsed_s}s {tick_interval}h {duration_ms}ms avg: {avg_ms}ms"
    )


class AutoFishTkApp:
    def __init__(self) -> None:
        self._magnification: int = 10

        self._cursor_position: tuple[int, int] | None = None
        self._is_fishing = False
        self._is_line_out = False
        self._exiting = False

        self._profiler = RollingProfiler(capacity=100)
        self._tick_interval: int = 0
        self._current_clock: float = 0.0
        self._start_clock: float | None = None
        self._last_tick_duration_ms = 0.0
        self._last_capture_duration_ms = 0.0
        self._last_detect_duration_ms = 0.0
        self._last_preview_duration_ms = 0.0
        self._last_record_duration_ms = 0.0
        self._last_effective_fps = 0.0
        self._last_rss_mb: float | None = None
        self._last_profile_log_at = 0.0

        self._viewer: Any | None = None
        self._capture_backend = create_capture_backend()
        self._camera = CursorCamera(
            self._magnification,
            capture_backend=self._capture_backend,
        )
        self._cursor_locator = CursorLocator(capture_backend=self._capture_backend)
        self._cursor_image = self._camera.blank()
        self._line_detector = FishingLineDetector()
        self._line_watcher = LineWatcher()
        self._minecraft_window: WindowInfo | None = None
        self._fishing_roi: tuple[int, int, int, int] | None = None
        self._tracking_box: tuple[int, int, int, int] | None = None
        self._detection_box: tuple[int, int, int, int] | None = None
        self._line_candidate: LineCandidate | None = None
        self._line_pixels = 0
        self._bite_detected = False

        self._root: Any | None = None
        self._status_var: Any | None = None
        self._line_state_var: Any | None = None
        self._debug_var: Any | None = None
        self._button: Any | None = None
        self._locate_button: Any | None = None
        self._calibrate_button: Any | None = None
        self._record_button: Any | None = None
        self._session_button: Any | None = None
        self._hotkey_hint_var: Any | None = None

        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._hotkeys_enabled = False
        self._consecutive_capture_failures = 0
        self._last_capture_error: str | None = None
        self._screenshot_index = 0
        self._recording_enabled = False
        self._last_recording_capture_at = 0.0
        self._last_saved_capture_name: str | None = None
        self._last_profile_name: str | None = None
        self._last_trace_name: str | None = None
        self._last_mark_clip_name: str | None = None
        self._session_recorder: SessionRecorder | None = None
        self._latest_window_frame: np.ndarray | None = None
        self._latest_debug_composite: np.ndarray | None = None

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        from autoangler.image_viewer_tk import ImageViewerTk

        root = tk.Tk()
        root.title("MC AutoAngler")
        root.geometry(self._load_window_geometry())
        root.minsize(860, 440)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self._quit)

        container = ttk.Frame(root, padding=8)
        container.pack(fill="both", expand=True)

        self._viewer = ImageViewerTk()
        self._viewer.frame(container).pack(fill="both", expand=True)

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(0, 8))

        self._locate_button = ttk.Button(
            controls, text="Locate Minecraft", command=self._locate_minecraft_window
        )
        self._locate_button.pack(side="left", padx=(0, 8))

        self._calibrate_button = ttk.Button(
            controls, text="Calibrate Box", command=self._calibrate_line
        )
        self._calibrate_button.pack(side="left", padx=(0, 8))

        self._record_button = ttk.Button(
            controls,
            text="Start Recording",
            command=self._toggle_recording,
        )
        self._record_button.pack(side="left", padx=(0, 8))

        self._session_button = ttk.Button(
            controls,
            text="Open Sessions",
            command=self._open_session_folder,
        )
        self._session_button.pack(side="left", padx=(0, 8))

        self._button = ttk.Button(controls, text="Start Fishing", command=self._toggle_fishing)
        self._button.pack(side="left")

        self._status_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self._status_var).pack(side="left", padx=12)
        self._line_state_var = tk.StringVar(value=line_state_text(is_line_out=self._is_line_out))
        ttk.Label(controls, textvariable=self._line_state_var).pack(side="left", padx=(0, 12))

        self._hotkey_hint_var = tk.StringVar(value=hotkey_hint_text(hotkeys_enabled=False))
        ttk.Label(container, textvariable=self._hotkey_hint_var).pack(anchor="w", pady=(0, 4))

        self._debug_var = tk.StringVar(value=self._debug_details_text())
        ttk.Label(
            container,
            textvariable=self._debug_var,
            justify="left",
            font="TkFixedFont",
        ).pack(anchor="w", pady=(0, 4))

        self._viewer.update(self._cursor_image)
        self._sync_line_state_indicator()

        self._root = root
        self._hotkeys_enabled = self._try_enable_hotkeys()
        logger.info("Hotkeys enabled: %s", self._hotkeys_enabled)
        logger.info("Capture backend: %s", self._capture_backend.backend_name)
        if self._hotkey_hint_var is not None:
            self._hotkey_hint_var.set(hotkey_hint_text(hotkeys_enabled=self._hotkeys_enabled))
        if not self._hotkeys_enabled and sys.platform == "darwin":
            messagebox.showwarning(
                "Enable Accessibility Permissions",
                "Global hotkeys (M/F6/F7/F8/F12/F9/ESC/F10) are disabled because this process "
                "is not trusted "
                "for "
                "input event monitoring.\n\n"
                "Fix: System Settings → Privacy & Security → Accessibility and Input Monitoring → "
                "enable your Terminal/IDE (the app you used to launch AutoAngler), then restart it."
                "\n\n"
                "You can still use the Start/Stop button.",
            )

        self._tick()
        root.mainloop()

    def _try_enable_hotkeys(self) -> bool:
        if sys.platform != "darwin":
            self._keyboard_listener.start()
            return True

        try:
            from Quartz import AXIsProcessTrusted  # type: ignore[import-not-found]

            if not AXIsProcessTrusted():
                return False
        except Exception:
            # If we can't check trust status, try to start anyway.
            pass

        try:
            self._keyboard_listener.start()
            return True
        except Exception:
            return False

    def _toggle_fishing(self) -> None:
        if self._is_fishing:
            self._stop()
        else:
            self._start()

    def _sync_line_state_indicator(self) -> None:
        if self._line_state_var is not None:
            self._line_state_var.set(line_state_text(is_line_out=self._is_line_out))

    def _toggle_recording(self) -> None:
        self._recording_enabled = not self._recording_enabled
        if self._recording_enabled:
            self._last_recording_capture_at = 0.0
            logger.info("Recording enabled")
        else:
            self._close_session_recorder()
            logger.info("Recording disabled")

        if self._record_button is not None:
            self._record_button.configure(
                text="Stop Recording" if self._recording_enabled else "Start Recording"
            )
        if self._status_var is not None:
            self._status_var.set(
                "Recording enabled" if self._recording_enabled else "Recording disabled"
            )
        if self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())

    def _start(self) -> None:
        self._begin_start(delay_ms=5000)

    def _start_hotkey(self) -> None:
        self._begin_start(delay_ms=0)

    def _begin_start(self, *, delay_ms: int) -> None:
        if self._root is None or self._button is None:
            return

        logger.info("Start fishing requested")
        if not self._ensure_tracking_context():
            return

        self._is_fishing = True
        self._is_line_out = False
        self._start_clock = None
        self._tick_interval = 0
        self._current_clock = 0.0
        self._bite_detected = False
        self._line_watcher.reset()

        self._button.configure(text="Stop Fishing")
        self._sync_line_state_indicator()

        if self._status_var is not None and delay_ms > 0:
            self._status_var.set("Starting in 5s... focus Minecraft")
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="start")
        if delay_ms > 0:
            self._root.after(delay_ms, self._cast_and_begin_tracking)
        else:
            self._cast_and_begin_tracking()

    def _stop(self) -> None:
        if self._button is None:
            return

        logger.info("Stop fishing requested")
        self._is_fishing = False
        self._is_line_out = False
        self._start_clock = None
        self._bite_detected = False
        self._line_watcher.reset()

        if not self._exiting:
            self._button.configure(text="Start Fishing")
            if self._status_var is not None:
                self._status_var.set("Stopped")
        self._sync_line_state_indicator()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="stop")
        if self._session_recorder is not None:
            self._session_recorder.finish_clips()

    def _cast_and_begin_tracking(self) -> None:
        if not self._is_fishing:
            return

        if not self._ensure_tracking_context():
            if self._status_var is not None:
                self._status_var.set("Could not locate Minecraft window")
            return

        if self._status_var is not None:
            self._status_var.set("Tracking line ROI...")
        logger.info("Tracking ROI %s in window %s", self._fishing_roi, self._minecraft_window)
        self._cast()

    def _locate_minecraft_window(self) -> bool:
        window = selected_minecraft_window()
        if window is None:
            logger.warning("Could not locate a Minecraft window")
            if self._status_var is not None:
                self._status_var.set("Could not find Minecraft window")
            return False

        self._minecraft_window = window
        self._fishing_roi = clamp_roi_to_window(default_fishing_roi(window), window)
        self._tracking_box = None
        self._detection_box = None
        self._line_candidate = None
        self._line_pixels = 0
        self._bite_detected = False
        self._line_watcher.reset()
        logger.info("Using Minecraft window '%s' at %s", window.title, window)
        logger.info("Fishing ROI set to %s", self._fishing_roi)
        if self._status_var is not None:
            self._status_var.set(f"Window: {window.title or '<untitled>'}")
        return True

    def _calibrate_line(self) -> None:
        if not self._ensure_tracking_context():
            return
        window_image = self._capture_window_image()
        if window_image is None:
            if self._status_var is not None:
                self._status_var.set("Could not capture Minecraft window")
            return

        roi_box, roi_frame = self._window_frame_and_roi(window_image.original)
        self._tracking_box = self._calibrated_tracking_box(roi_frame)
        self._detection_box = self._default_detection_box(roi_frame)
        self._line_watcher.reset()
        self._bite_detected = False
        self._cursor_image = self._build_tracking_preview(
            window_image.original,
            roi_box,
            roi_frame,
        )
        if self._viewer is not None:
            self._viewer.update(self._cursor_image)
        self._maybe_save_debug_screenshot("calibrate", image=self._cursor_image.original)
        if self._status_var is not None:
            self._status_var.set("Calibrated tracking box")

    def _ensure_tracking_context(self) -> bool:
        if self._minecraft_window is not None and self._fishing_roi is not None:
            return True
        return self._locate_minecraft_window()

    def _capture_window_image(self) -> CursorImage | None:
        if self._minecraft_window is None:
            return None

        window = self._minecraft_window
        window_box = (
            window.left,
            window.top,
            window.left + window.width,
            window.top + window.height,
        )

        try:
            window_image = self._camera.capture_bbox(window_box, magnify=False)
            self._consecutive_capture_failures = 0
            self._last_capture_error = None
            return window_image
        except Exception as exc:
            self._consecutive_capture_failures += 1
            self._last_capture_error = str(exc)
            logger.debug(
                "Capture failed (%s consecutive). window=%s roi=%s cursor_position=%s error=%s",
                self._consecutive_capture_failures,
                self._minecraft_window,
                self._fishing_roi,
                self._cursor_position,
                exc,
            )
            if self._consecutive_capture_failures == 1:
                self._maybe_save_debug_screenshot("capture-failure")
            if self._consecutive_capture_failures >= 3:
                self._minecraft_window = None
                self._fishing_roi = None
                self._tracking_box = None
                self._detection_box = None
            return None

    def _calibrated_tracking_box(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        self._line_candidate = self._line_detector.find_line(frame)
        tracking_box = self._default_tracking_box(frame)
        if self._line_candidate is not None:
            logger.info(
                "Detected line candidate center=%s bbox=%s pixels=%s; using cursor tracking box %s",
                self._line_candidate.center,
                self._line_candidate.bbox,
                self._line_candidate.pixel_count,
                tracking_box,
            )
        else:
            logger.warning(
                "Could not detect fishing line; using cursor tracking box %s",
                tracking_box,
            )
        return tracking_box

    def _default_tracking_box(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        if self._minecraft_window is not None and self._fishing_roi is not None:
            anchor = cursor_anchor_in_roi(self._minecraft_window, self._fishing_roi)
            return centered_tracking_box(frame.shape, center=anchor)
        return centered_tracking_box(frame.shape)

    def _default_detection_box(self, frame: np.ndarray) -> tuple[int, int, int, int]:
        frame_height, frame_width = frame.shape[:2]
        if self._minecraft_window is not None and self._fishing_roi is not None:
            anchor_x, anchor_y = cursor_anchor_in_roi(self._minecraft_window, self._fishing_roi)
        else:
            anchor_x, anchor_y = frame_width // 2, frame_height // 2

        width = 44
        height = 36
        left = anchor_x - 24
        top = anchor_y + 8
        return self._clamp_box(frame.shape, left=left, top=top, width=width, height=height)

    @staticmethod
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

    def _window_frame_and_roi(
        self, window_frame: np.ndarray
    ) -> tuple[tuple[int, int, int, int], np.ndarray]:
        if self._minecraft_window is None or self._fishing_roi is None:
            raise RuntimeError("Tracking context is not ready.")
        roi_box = window_relative_box(self._fishing_roi, self._minecraft_window)
        x1, y1, x2, y2 = roi_box
        return roi_box, window_frame[y1:y2, x1:x2]

    def _tracking_frame(self, frame: np.ndarray) -> tuple[tuple[int, int, int, int], np.ndarray]:
        tracking_box = self._tracking_box
        if tracking_box is None:
            tracking_box = self._default_tracking_box(frame)
        x1, y1, x2, y2 = tracking_box
        return tracking_box, frame[y1:y2, x1:x2]

    def _detection_frame(
        self, frame: np.ndarray
    ) -> tuple[tuple[int, int, int, int], np.ndarray]:
        detection_box = self._detection_box
        if detection_box is None:
            detection_box = self._default_detection_box(frame)
        x1, y1, x2, y2 = detection_box
        return detection_box, frame[y1:y2, x1:x2]

    def _build_tracking_preview(
        self,
        window_frame: np.ndarray,
        roi_box: tuple[int, int, int, int],
        roi_frame: np.ndarray,
    ) -> CursorImage:
        tracking_box, _tracking_frame = self._tracking_frame(roi_frame)
        detection_box, detection_frame = self._detection_frame(roi_frame)
        processed_tracking = self._line_detector.threshold_dark_pixels(detection_frame)
        black_pixel_count = int(np.sum(processed_tracking == 0))

        annotated = window_frame.copy()
        roi_left, roi_top, roi_right, roi_bottom = roi_box
        cv2.rectangle(
            annotated,
            (roi_left, roi_top),
            (roi_right, roi_bottom),
            color=160,
            thickness=1,
        )

        x1, y1, x2, y2 = tracking_box
        cv2.rectangle(
            annotated,
            (roi_left + x1, roi_top + y1),
            (roi_left + x2, roi_top + y2),
            color=0,
            thickness=1,
        )

        dx1, dy1, dx2, dy2 = detection_box
        cv2.rectangle(
            annotated,
            (roi_left + dx1, roi_top + dy1),
            (roi_left + dx2, roi_top + dy2),
            color=64,
            thickness=1,
        )

        if self._line_candidate is not None:
            lx1, ly1, lx2, ly2 = self._line_candidate.bbox
            cv2.rectangle(
                annotated,
                (roi_left + lx1, roi_top + ly1),
                (roi_left + lx2, roi_top + ly2),
                color=96,
                thickness=1,
            )
            cv2.circle(
                annotated,
                (
                    roi_left + self._line_candidate.center[0],
                    roi_top + self._line_candidate.center[1],
                ),
                radius=2,
                color=96,
                thickness=-1,
            )

        return CursorImage(
            original=annotated,
            computer=processed_tracking,
            black_pixel_count=black_pixel_count,
        )

    def _build_debug_composite(self) -> np.ndarray:
        left = self._to_bgr(self._cursor_image.original)
        right = self._to_bgr(self._cursor_image.computer)

        max_mask_scale = max(1, left.shape[0] // max(right.shape[0], 1))
        mask_scale = max(1, min(8, max_mask_scale))
        right = cv2.resize(
            right,
            (right.shape[1] * mask_scale, right.shape[0] * mask_scale),
            interpolation=cv2.INTER_NEAREST,
        )

        gap = 16
        text_lines = [
            self._status_text_value() or "status:-",
            line_state_text(is_line_out=self._is_line_out),
            f"track:{self._tracking_box} detect:{self._detection_box}",
            (
                f"line_px:{self._line_pixels} trig:{self._line_watcher.trigger_pixels} "
                f"weak:{self._line_watcher.weak_frames}/{self._line_watcher.min_frames}"
            ),
            f"mark:{self._last_mark_clip_name or '-'}",
        ]
        line_height = 22
        text_height = (line_height * len(text_lines)) + 16
        panel_width = max(right.shape[1], 360)
        canvas_height = max(left.shape[0], right.shape[0] + gap + text_height)
        canvas_width = left.shape[1] + gap + panel_width
        canvas = np.full((canvas_height, canvas_width, 3), 24, dtype=np.uint8)

        canvas[: left.shape[0], : left.shape[1]] = left
        right_left = left.shape[1] + gap
        canvas[: right.shape[0], right_left : right_left + right.shape[1]] = right

        text_y = right.shape[0] + gap + 18
        for line in text_lines:
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

    @staticmethod
    def _to_bgr(frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            return cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        return frame

    def _status_text_value(self) -> str:
        if self._status_var is None or not hasattr(self._status_var, "get"):
            return ""
        return str(self._status_var.get()).strip()

    def _capture_debug_screenshot(self) -> None:
        if self._fishing_roi is not None and self._minecraft_window is not None:
            self._update_image()
        filename = self._save_screenshot("screenshot")
        if self._status_var is not None:
            self._status_var.set(f"Saved screenshot: {filename.name}")
        if self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())

    def _open_session_folder(self) -> Path:
        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            folder = Path(log_path).expanduser().resolve().parent
        else:
            folder = (Path.home() / ".autoangler" / "sessions").resolve()
        folder.mkdir(parents=True, exist_ok=True)

        if sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        elif sys.platform == "win32":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)

        logger.info("Opened session folder %s", folder)
        if self._status_var is not None:
            self._status_var.set(f"Opened sessions: {folder.name}")
        if self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())
        return folder

    def _window_state_path(self) -> Path:
        return Path.home() / ".autoangler" / "window.json"

    def _load_window_geometry(self) -> str:
        try:
            data = json.loads(self._window_state_path().read_text())
        except Exception:
            return DEFAULT_WINDOW_GEOMETRY

        geometry = str(data.get("geometry", "")).strip()
        if self._is_window_geometry(geometry):
            return geometry
        return DEFAULT_WINDOW_GEOMETRY

    def _save_window_geometry(self) -> Path | None:
        root = self._root
        if root is None:
            return None

        geometry = str(root.geometry()).strip()
        if not self._is_window_geometry(geometry):
            return None

        state_path = self._window_state_path()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"geometry": geometry}, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved window geometry %s to %s", geometry, state_path)
        return state_path

    @staticmethod
    def _is_window_geometry(geometry: str) -> bool:
        return re.fullmatch(r"\d+x\d+[+-]\d+[+-]\d+", geometry) is not None

    def _mark_bite(self) -> Path:
        now = monotonic()
        path = self._append_trace_row(now=now, event="mark")
        self._capture_mark_clip("mark", now=now)
        logger.info("Manual bite mark")
        if self._status_var is not None:
            self._status_var.set("Marked bite")
        if self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())
        return path

    def _mark_reel(self) -> Path:
        now = monotonic()
        path = self._append_trace_row(now=now, event="mark_reel")
        self._capture_mark_clip("mark-reel", now=now)
        logger.info("Manual reel mark")
        if self._is_fishing and self._is_line_out:
            self._reel_and_recast()
            status = "Marked bite and reeled"
        else:
            status = "Marked reel"
        if self._status_var is not None:
            self._status_var.set(status)
        if self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())
        return path

    def _save_screenshot(self, label: str, *, image: np.ndarray | None = None) -> Path:
        from PIL import Image

        if image is None:
            image = self._cursor_image.original

        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            filename = build_session_capture_path(
                Path(log_path),
                f"{label}-{self._screenshot_index:02d}",
            )
        else:
            filename = (
                Path.home()
                / ".autoangler"
                / f"{label}-{self._screenshot_index:02d}.png"
            )

        filename.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(image.astype("uint8"), mode="L").save(filename)
        logger.info("Saved screenshot to %s", filename)
        self._screenshot_index += 1
        self._last_saved_capture_name = filename.name
        return filename

    def _close_session_recorder(self) -> None:
        if self._session_recorder is None:
            return
        self._session_recorder.close()
        self._session_recorder = None

    def _append_trace_row(self, *, now: float, event: str) -> Path:
        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            trace_path = build_session_trace_path(Path(log_path))
        else:
            trace_path = Path.home() / ".autoangler" / "trace.csv"

        trace_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not trace_path.exists() or trace_path.stat().st_size == 0
        with trace_path.open("a", encoding="utf-8", newline="") as handle:
            writer = DictWriter(
                handle,
                fieldnames=[
                    "time_s",
                    "event",
                    "is_fishing",
                    "is_line_out",
                    "line_pixels",
                    "trigger_pixels",
                    "weak_frames",
                    "bite_detected",
                ],
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "time_s": f"{now:.3f}",
                    "event": event,
                    "is_fishing": int(self._is_fishing),
                    "is_line_out": int(self._is_line_out),
                    "line_pixels": self._line_pixels,
                    "trigger_pixels": self._line_watcher.trigger_pixels,
                    "weak_frames": self._line_watcher.weak_frames,
                    "bite_detected": int(self._bite_detected),
                }
            )

        self._last_trace_name = trace_path.name
        return trace_path

    def _append_profile_row(
        self,
        *,
        now: float,
        total_ms: float,
        capture_ms: float,
        detect_ms: float,
        preview_ms: float,
        record_ms: float,
    ) -> Path:
        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            profile_path = build_session_profile_path(Path(log_path))
        else:
            profile_path = Path.home() / ".autoangler" / "profile.csv"

        profile_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not profile_path.exists() or profile_path.stat().st_size == 0
        with profile_path.open("a", encoding="utf-8", newline="") as handle:
            writer = DictWriter(
                handle,
                fieldnames=[
                    "time_s",
                    "is_fishing",
                    "is_line_out",
                    "total_ms",
                    "capture_ms",
                    "detect_ms",
                    "preview_ms",
                    "record_ms",
                    "line_pixels",
                    "trigger_pixels",
                ],
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "time_s": f"{now:.3f}",
                    "is_fishing": int(self._is_fishing),
                    "is_line_out": int(self._is_line_out),
                    "total_ms": f"{total_ms:.1f}",
                    "capture_ms": f"{capture_ms:.1f}",
                    "detect_ms": f"{detect_ms:.1f}",
                    "preview_ms": f"{preview_ms:.1f}",
                    "record_ms": f"{record_ms:.1f}",
                    "line_pixels": self._line_pixels,
                    "trigger_pixels": self._line_watcher.trigger_pixels,
                }
            )

        self._last_profile_name = profile_path.name
        return profile_path

    def _maybe_save_debug_screenshot(
        self, label: str, *, image: np.ndarray | None = None
    ) -> Path | None:
        if not logger.isEnabledFor(logging.DEBUG):
            return None
        return self._save_screenshot(label, image=image)

    def _maybe_record_frame(self, *, now: float) -> Path | None:
        if not self._recording_enabled or not self._is_fishing:
            return None

        recorder = self._ensure_session_recorder()
        if (
            recorder is not None
            and self._latest_window_frame is not None
            and self._latest_debug_composite is not None
        ):
            recorder.record_frame(
                now=now,
                raw_window_frame=self._latest_window_frame,
                debug_frame=self._latest_debug_composite,
            )

        interval_ms = int(os.environ.get("AUTOANGLER_RECORD_INTERVAL_MS", "500"))
        interval_s = max(0.05, interval_ms / 1000)
        if self._last_recording_capture_at and (now - self._last_recording_capture_at) < interval_s:
            return None

        filename = self._save_screenshot("recording")
        self._last_recording_capture_at = now
        return filename

    def _debug_details_text(self) -> str:
        candidate_text = "candidate:none"
        if self._line_candidate is not None:
            candidate_text = (
                f"candidate:{self._line_candidate.center} "
                f"bbox:{self._line_candidate.bbox} "
                f"pixels:{self._line_candidate.pixel_count}"
            )

        last_error = self._last_capture_error or "-"
        last_capture = self._last_saved_capture_name or "-"
        last_profile = self._last_profile_name or "-"
        last_trace = self._last_trace_name or "-"
        last_mark = self._last_mark_clip_name or "-"
        window_video = (
            self._session_recorder.window_video_path.name
            if self._session_recorder is not None
            else "-"
        )
        debug_video = (
            self._session_recorder.debug_video_path.name
            if self._session_recorder is not None
            else "-"
        )
        return (
            f"recording:{'on' if self._recording_enabled else 'off'} "
            f"roi:{self._fishing_roi} track:{self._tracking_box} "
            f"detect:{self._detection_box} line_px:{self._line_pixels}\n"
            f"perf:{self._profile_summary_text()}\n"
            f"{candidate_text}\n"
            f"videos:{window_video},{debug_video} last_mark:{last_mark}\n"
            f"last_capture:{last_capture} last_profile:{last_profile} "
            f"last_trace:{last_trace} last_error:{last_error}"
        )

    def _profile_summary_text(self) -> str:
        rss_text = "-" if self._last_rss_mb is None else f"{self._last_rss_mb:.1f}MB"
        top_stage = self._top_profile_stage_text()
        return (
            f"fps:{self._last_effective_fps:.1f} "
            f"tick:{self._last_tick_duration_ms:.1f}ms "
            f"cap:{self._last_capture_duration_ms:.1f}ms "
            f"detect:{self._last_detect_duration_ms:.1f}ms "
            f"preview:{self._last_preview_duration_ms:.1f}ms "
            f"rec:{self._last_record_duration_ms:.1f}ms "
            f"{top_stage} "
            f"rss:{rss_text}"
        )

    def _top_profile_stage_text(self) -> str:
        stage_name, duration_ms = max(
            (
                ("capture", self._last_capture_duration_ms),
                ("detect", self._last_detect_duration_ms),
                ("preview", self._last_preview_duration_ms),
                ("record", self._last_record_duration_ms),
            ),
            key=lambda item: item[1],
        )
        pct = 0.0
        if self._last_tick_duration_ms > 0:
            pct = (duration_ms / self._last_tick_duration_ms) * 100
        return f"top:{stage_name} {duration_ms:.1f}ms ({pct:.0f}%)"

    def _ensure_session_recorder(self) -> SessionRecorder | None:
        if self._session_recorder is not None:
            return self._session_recorder

        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if not log_path:
            return None

        self._session_recorder = SessionRecorder(Path(log_path))
        return self._session_recorder

    def _maybe_log_profile(self, *, now: float) -> None:
        if not (self._is_fishing or self._recording_enabled):
            return

        interval_s = float(os.environ.get("AUTOANGLER_PROFILE_LOG_INTERVAL_S", "15"))
        if self._last_profile_log_at and (now - self._last_profile_log_at) < interval_s:
            return

        self._last_profile_log_at = now
        logger.info("PROFILE %s", self._profile_summary_text())

    def _capture_mark_clip(self, label: str, *, now: float) -> Path | None:
        if not self._recording_enabled:
            return None

        recorder = self._ensure_session_recorder()
        if recorder is None:
            return None

        clip_path = recorder.mark(label, now=now)
        self._last_mark_clip_name = clip_path.name
        return clip_path

    @staticmethod
    def _get_virtual_screen_center() -> tuple[int, int] | None:
        bounds = get_virtual_screen_bounds()
        if bounds is None:
            return None
        return ((bounds.left + bounds.right) // 2, (bounds.top + bounds.bottom) // 2)

    @staticmethod
    def _get_active_window_center() -> tuple[int, int] | None:
        """
        Best-effort active window center (helps for windowed Minecraft).
        """
        try:
            win = pyautogui.getActiveWindow()
            if win is None:
                return None
            if not all(hasattr(win, attr) for attr in ("left", "top", "width", "height")):
                return None
            if win.width <= 0 or win.height <= 0:
                return None
            return (int(win.left + win.width / 2), int(win.top + win.height / 2))
        except Exception:
            return None

    def _cast(self) -> None:
        if self._root is None:
            return

        logger.info("Cast")
        self._bite_detected = False
        self._line_watcher.reset()
        self._use_rod()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="cast")
        self._root.after(3000, self._mark_line_out)

    def _mark_line_out(self) -> None:
        if self._is_fishing:
            self._is_line_out = True
            self._sync_line_state_indicator()

    def _reel(self) -> None:
        logger.info("Reel")
        self._use_rod()
        self._is_line_out = False
        self._sync_line_state_indicator()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="reel")

    def _reel_and_recast(self) -> None:
        self._reel()
        if self._root is None:
            self._cast()
            return

        recast_delay_ms = int(os.environ.get("AUTOANGLER_RECAST_DELAY_MS", "350"))
        self._root.after(max(0, recast_delay_ms), self._cast)

    @staticmethod
    def _use_rod() -> None:
        pyautogui.rightClick()

    def _preview_target(self) -> tuple[int, int] | None:
        if self._cursor_position is not None:
            return self._cursor_position
        return self._get_active_window_center() or self._get_virtual_screen_center()

    def _should_capture_preview(self) -> bool:
        return self._is_fishing or (
            self._minecraft_window is not None and self._fishing_roi is not None
        )

    def _tick(self) -> None:
        if self._root is None:
            return

        start_time = monotonic()
        capture_duration_ms = 0.0
        detect_duration_ms = 0.0
        preview_duration_ms = 0.0
        record_duration_ms = 0.0

        if self._should_capture_preview():
            (
                capture_duration_ms,
                detect_duration_ms,
                preview_duration_ms,
            ) = self._update_image_profiled()
            tick_now = monotonic()
            record_start = monotonic()
            self._maybe_record_frame(now=tick_now)
            record_duration_ms = round((monotonic() - record_start) * 1000, 1)
            if self._recording_enabled and self._is_fishing:
                self._append_trace_row(now=tick_now, event="tick")

        if self._is_fish_on():
            self._reel_and_recast()

        duration_ms = round((monotonic() - start_time) * 1000, 1)
        if self._should_capture_preview():
            self._append_profile_row(
                now=monotonic(),
                total_ms=duration_ms,
                capture_ms=capture_duration_ms,
                detect_ms=detect_duration_ms,
                preview_ms=preview_duration_ms,
                record_ms=record_duration_ms,
            )

        if self._is_fishing:
            now = time()
            if self._start_clock is None:
                self._current_clock = now
                self._start_clock = now

            next_clock_position = self._current_clock + MINECRAFT_IRL_SECONDS_PER_MC_HOUR
            if now >= next_clock_position:
                self._tick_interval = (self._tick_interval + 1) % 23
                self._current_clock = next_clock_position

            self._profiler.add(
                TickProfile(
                    total_ms=duration_ms,
                    capture_ms=capture_duration_ms,
                    detect_ms=detect_duration_ms,
                    preview_ms=preview_duration_ms,
                    record_ms=record_duration_ms,
                )
            )
            summary = self._profiler.summary()
            self._last_tick_duration_ms = duration_ms
            self._last_capture_duration_ms = capture_duration_ms
            self._last_detect_duration_ms = detect_duration_ms
            self._last_preview_duration_ms = preview_duration_ms
            self._last_record_duration_ms = record_duration_ms
            avg_ms = round(summary.avg_total_ms, 1)
            avg_capture_ms = round(summary.avg_capture_ms, 1)
            avg_detect_ms = round(summary.avg_detect_ms, 1)
            avg_preview_ms = round(summary.avg_preview_ms, 1)
            avg_record_ms = round(summary.avg_record_ms, 1)
            self._last_effective_fps = round((1000.0 / avg_ms), 1) if avg_ms > 0 else 0.0
            self._last_rss_mb = self._current_rss_mb()

            elapsed_s = int(now - self._start_clock)
            status = tracking_status_text(
                line_pixels=self._cursor_image.black_pixel_count,
                watcher=self._line_watcher,
                is_line_out=self._is_line_out,
                bite_detected=self._bite_detected,
                elapsed_s=elapsed_s,
                tick_interval=self._tick_interval,
                duration_ms=duration_ms,
                avg_ms=avg_ms,
            )
            if self._status_var is not None:
                self._status_var.set(status)
            if self._debug_var is not None:
                self._debug_var.set(self._debug_details_text())
            logger.debug(
                (
                    "PROFILE_DETAIL avg_tick_ms=%.1f avg_capture_ms=%.1f "
                    "avg_detect_ms=%.1f avg_preview_ms=%.1f "
                    "avg_record_ms=%.1f fps=%.1f rss_mb=%s"
                ),
                avg_ms,
                avg_capture_ms,
                avg_detect_ms,
                avg_preview_ms,
                avg_record_ms,
                self._last_effective_fps,
                "-" if self._last_rss_mb is None else f"{self._last_rss_mb:.1f}",
            )
            self._maybe_log_profile(now=monotonic())
        elif self._debug_var is not None:
            self._debug_var.set(self._debug_details_text())

        self._sync_line_state_indicator()

        if not self._exiting:
            self._root.after(33, self._tick)

    def _update_image(self) -> None:
        self._update_image_profiled()

    def _update_image_profiled(self) -> tuple[float, float, float]:
        capture_duration_ms = 0.0
        detect_duration_ms = 0.0
        preview_duration_ms = 0.0

        if self._viewer is None:
            return capture_duration_ms, detect_duration_ms, preview_duration_ms
        if self._fishing_roi is None:
            self._latest_window_frame = None
            self._latest_debug_composite = None
            target = self._preview_target()
            if target is None:
                return capture_duration_ms, detect_duration_ms, preview_duration_ms
            try:
                capture_start = monotonic()
                self._cursor_image = self._camera.capture(target)
                capture_duration_ms = round((monotonic() - capture_start) * 1000, 1)
                preview_start = monotonic()
                self._viewer.update(self._cursor_image)
                preview_duration_ms = round((monotonic() - preview_start) * 1000, 1)
            except Exception:
                return capture_duration_ms, detect_duration_ms, preview_duration_ms
            return capture_duration_ms, detect_duration_ms, preview_duration_ms

        capture_start = monotonic()
        window_image = self._capture_window_image()
        capture_duration_ms = round((monotonic() - capture_start) * 1000, 1)
        if window_image is None:
            self._latest_window_frame = None
            self._latest_debug_composite = None
            return capture_duration_ms, detect_duration_ms, preview_duration_ms

        window_frame = window_image.original
        detect_start = monotonic()
        roi_box, roi_frame = self._window_frame_and_roi(window_frame)
        self._line_candidate = self._line_detector.find_line(roi_frame)
        auto_calibrated = False
        if self._tracking_box is None and self._is_line_out:
            self._tracking_box = self._calibrated_tracking_box(roi_frame)
            self._detection_box = self._default_detection_box(roi_frame)
            auto_calibrated = True
            if self._status_var is not None:
                self._status_var.set("Auto-calibrated cursor box")

        self._cursor_image = self._build_tracking_preview(window_frame, roi_box, roi_frame)
        self._line_pixels = self._cursor_image.black_pixel_count
        self._bite_detected = self._line_watcher.observe(
            self._line_pixels,
            active=self._is_fishing and self._is_line_out,
        )
        detect_duration_ms = round((monotonic() - detect_start) * 1000, 1)

        preview_start = monotonic()
        self._latest_window_frame = window_frame.copy()
        self._latest_debug_composite = self._build_debug_composite()
        if auto_calibrated and self._line_candidate is None:
            self._maybe_save_debug_screenshot("line-miss", image=self._cursor_image.original)

        self._viewer.update(self._cursor_image)
        preview_duration_ms = round((monotonic() - preview_start) * 1000, 1)

        return capture_duration_ms, detect_duration_ms, preview_duration_ms

    def _is_fish_on(self) -> bool:
        return self._is_fishing and self._is_line_out and self._bite_detected

    def _on_key_press(self, key) -> None:
        root = self._root
        if root is None:
            return

        if key == keyboard.Key.f7:
            root.after(0, self._toggle_recording)
        elif key == keyboard.Key.f8:
            root.after(0, self._capture_debug_screenshot)
        elif key == keyboard.Key.f12:
            root.after(0, self._start_hotkey)
        elif key == keyboard.Key.f9:
            root.after(0, self._calibrate_line)
        elif key == keyboard.Key.esc:
            root.after(0, self._stop)
        elif key == keyboard.Key.f10:
            root.after(0, self._quit)
        elif getattr(key, "char", "").lower() == "m":
            root.after(0, self._mark_bite)
        elif key == keyboard.Key.f6:
            root.after(0, self._mark_reel)

    def _quit(self) -> None:
        if self._exiting:
            return

        self._exiting = True
        self._save_window_geometry()
        self._stop()
        try:
            self._keyboard_listener.stop()
        finally:
            self._close_session_recorder()
            self._capture_backend.close()
            if self._root is not None:
                self._root.destroy()

    @staticmethod
    def _rolling_average(values: np.ndarray) -> float:
        non_zero = values[values > 0]
        if non_zero.size == 0:
            return 0.0
        return float(np.average(non_zero))

    @staticmethod
    def _current_rss_mb() -> float | None:
        if resource is None:
            return None
        try:
            usage = resource.getrusage(resource.RUSAGE_SELF)
        except Exception:
            return None

        rss = float(usage.ru_maxrss)
        if sys.platform == "darwin":
            return rss / (1024 * 1024)
        return rss / 1024
