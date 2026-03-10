from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import sys
from csv import DictWriter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from time import monotonic, sleep, time
from typing import Any

import cv2
import numpy as np
import pyautogui
from pynput import keyboard

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

from autoangler.async_pipeline import (
    RecordingEvent,
    RecordingWorker,
    VisionRequest,
    VisionResult,
    VisionWorker,
)
from autoangler.audio_probe import AudioHintEvent, AudioHintMonitor
from autoangler.capture_backend import create_capture_backend
from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_image import CursorImage
from autoangler.cursor_locator import CursorLocator
from autoangler.line_detector import FishingLineDetector, LineCandidate, centered_tracking_box
from autoangler.line_watcher import LineWatcher
from autoangler.logging_utils import (
    build_session_capture_path,
    build_session_profile_path,
    build_session_trace_path,
)
from autoangler.minecraft_window import WindowInfo, selected_minecraft_window
from autoangler.profiling import RollingProfiler, TickProfile
from autoangler.rod_detector import RodDetector
from autoangler.roi import (
    clamp_roi_to_window,
    cursor_anchor_in_roi,
    default_fishing_roi,
    window_relative_box,
)
from autoangler.runtime_config import DelayRange, RuntimeConfig
from autoangler.screen import get_virtual_screen_bounds

# The default pause sometimes causes the cast to also retrieve
pyautogui.PAUSE = 0.01

MINECRAFT_TICKS_PER_MC_DAY = 24000
MINECRAFT_TICKS_PER_HOUR = MINECRAFT_TICKS_PER_MC_DAY / 24
MINECRAFT_IRL_MINUTES_PER_MC_DAY = 20
MINECRAFT_IRL_MINUTES_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_DAY / 24
MINECRAFT_IRL_SECONDS_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_HOUR * 60

logger = logging.getLogger(__name__)
DEFAULT_WINDOW_GEOMETRY = "384x328+300+0"
GUIDE_STROKE_PX = 2
IDLE_CAPTURE_INTERVAL_S = 0.5
AUTO_STRAFE_STEP_MS = 300
AUTO_STRAFE_MAX_OFFSET_STEPS = 4
AUTO_MOUSE_DRIFT_STEP_X_PX = 4
AUTO_MOUSE_DRIFT_STEP_Y_PX = 2
AUTO_MOUSE_DRIFT_MAX_X_PX = 16
AUTO_MOUSE_DRIFT_MAX_Y_PX = 8
AUTO_MOUSE_DRIFT_STEP_DELAY_MS = 80


@dataclass
class MovementState:
    current_strafe_offset_steps: int = 0
    current_mouse_offset_x_px: int = 0
    current_mouse_offset_y_px: int = 0


def hotkey_hint_text(hotkeys_enabled: bool) -> str:
    suffix = "" if hotkeys_enabled else " (global hotkeys disabled)"
    return (
        "Hotkeys: F7 record | F8 manual cast/reel + detector mark | "
        f"F9 locate+calibrate | F10 debug | F12 start/stop | Cmd+Q exit{suffix}"
    )


def catch_count_text(count: int) -> str:
    return str(count)


def cast_ratio_text(*, bites: int, casts: int) -> str:
    return f"{bites} / {casts}"


def main_window_minsize() -> tuple[int, int]:
    from autoangler.image_viewer_tk import PREVIEW_MAX_HEIGHT, PREVIEW_MAX_WIDTH

    return PREVIEW_MAX_WIDTH + 24, PREVIEW_MAX_HEIGHT + 88


def main_window_summary_text(*, fps: float, tick_ms: float) -> str:
    return f"FPS {fps:.1f} | {int(round(tick_ms))}ms"


def normalized_main_window_geometry(saved_geometry: str) -> str:
    width, height = main_window_minsize()
    position = window_position_from_geometry(saved_geometry)
    if position is None:
        return DEFAULT_WINDOW_GEOMETRY
    return f"{width}x{height}{position}"


def window_position_from_geometry(geometry: str) -> str | None:
    match = re.fullmatch(r"\d+x\d+([+-]\d+)([+-]\d+)", geometry.strip())
    if match is None:
        return None
    return f"{match.group(1)}{match.group(2)}"


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
    @staticmethod
    def _main_window_resizable() -> tuple[bool, bool]:
        return False, False

    def __init__(
        self,
        *,
        runtime_config: RuntimeConfig | None = None,
        audio_monitor: AudioHintMonitor | None = None,
    ) -> None:
        self._magnification: int = 10
        self._runtime_config = runtime_config or RuntimeConfig()
        self._random = random.Random()

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
        self._last_context_refresh_at = 0.0
        self._last_bite_indicator_at = 0.0
        self._last_vision_age_ms = 0.0
        self._vision_dropped_frames = 0
        self._record_queue_depth = 0
        self._record_dropped_frames = 0
        self._preview_state = "neutral"

        self._viewer: Any | None = None
        self._debug_viewer: Any | None = None
        self._capture_backend = create_capture_backend()
        self._camera = CursorCamera(
            self._magnification,
            capture_backend=self._capture_backend,
        )
        self._cursor_locator = CursorLocator(capture_backend=self._capture_backend)
        self._cursor_image = self._camera.blank()
        self._line_detector = FishingLineDetector()
        self._rod_detector = RodDetector()
        self._line_watcher = LineWatcher()
        self._minecraft_window: WindowInfo | None = None
        self._fishing_roi: tuple[int, int, int, int] | None = None
        self._tracking_box: tuple[int, int, int, int] | None = None
        self._detection_box: tuple[int, int, int, int] | None = None
        self._line_candidate: LineCandidate | None = None
        self._line_pixels = 0
        self._bite_detected = False
        self._rod_in_hand = False
        self._catch_count = 0
        self._cast_count = 0
        self._topmost_enabled = True

        self._root: Any | None = None
        self._debug_window: Any | None = None
        self._status_var: Any | None = None
        self._line_state_var: Any | None = None
        self._debug_var: Any | None = None
        self._summary_var: Any | None = None
        self._catch_var: Any | None = None
        self._recording_dot: Any | None = None
        self._fishing_dot: Any | None = None
        self._bite_dot: Any | None = None
        self._topmost_var: Any | None = None
        self._cod_icon: Any | None = None
        self._button: Any | None = None
        self._locate_button: Any | None = None
        self._calibrate_button: Any | None = None
        self._record_button: Any | None = None
        self._session_button: Any | None = None
        self._hotkey_hint_var: Any | None = None
        self._auto_strafe_var: Any | None = None
        self._auto_strafe_enabled = self._runtime_config.auto_strafe_enabled
        self._movement_state = MovementState()

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
        self._latest_window_frame: np.ndarray | None = None
        self._latest_debug_composite: np.ndarray | None = None
        self._audio_monitor = audio_monitor
        self._audio_monitor_started = False
        self._last_audio_hint: AudioHintEvent | None = None
        self._vision_worker: VisionWorker | None = None
        self._recording_worker: RecordingWorker | None = None
        self._vision_epoch = 0
        self._next_vision_seq = 0
        self._last_applied_vision_seq = 0
        self._last_vision_completed_at: float | None = None
        self._last_vision_submit_at = 0.0

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        from autoangler.image_viewer_tk import ImageViewerTk

        root = tk.Tk()
        root.title("MC AutoAngler")
        root.geometry(self._load_window_geometry())
        root.minsize(*main_window_minsize())
        root.resizable(*self._main_window_resizable())
        root.attributes("-topmost", self._topmost_enabled)
        root.protocol("WM_DELETE_WINDOW", self._quit)
        root.bind("<Command-q>", lambda _event: self._quit())
        root.bind("<Command-Q>", lambda _event: self._quit())

        self._topmost_var = tk.BooleanVar(value=self._topmost_enabled)
        self._status_var = tk.StringVar(value="")
        self._line_state_var = tk.StringVar(value=line_state_text(is_line_out=self._is_line_out))
        self._summary_var = tk.StringVar(value="FPS -- | Tick --")
        self._catch_var = tk.StringVar(value=cast_ratio_text(bites=0, casts=0))
        self._debug_var = tk.StringVar(value=self._debug_stats_text())
        self._auto_strafe_var = tk.BooleanVar(value=self._auto_strafe_enabled)

        root.config(menu=self._build_menu(root))
        container = ttk.Frame(root, padding=8)
        container.pack(fill="both", expand=True)

        self._viewer = ImageViewerTk(dual=False)
        self._viewer.frame(container).pack(fill="both", expand=True)

        status_row = ttk.Frame(container)
        status_row.pack(fill="x", pady=(8, 0))
        self._recording_dot = self._build_indicator(status_row, label="Rec")
        self._fishing_dot = self._build_indicator(status_row, label="Fishing")
        self._bite_dot = self._build_indicator(status_row, label="Bite")
        try:
            icon_path = resources.files("autoangler.assets").joinpath("Cod.gif")
            self._cod_icon = tk.PhotoImage(file=str(icon_path)).subsample(14, 14)
        except Exception:
            self._cod_icon = None
        ttk.Label(status_row, image=self._cod_icon).pack(side="left", padx=(0, 4))
        ttk.Label(status_row, textvariable=self._catch_var).pack(side="left", padx=(0, 12))
        ttk.Label(status_row, textvariable=self._summary_var).pack(side="left")

        controls_row = ttk.Frame(container)
        controls_row.pack(fill="x", pady=(6, 0))
        ttk.Checkbutton(
            controls_row,
            text="Auto-Strafe",
            variable=self._auto_strafe_var,
            command=self._toggle_auto_strafe,
        ).pack(side="left")

        self._build_debug_window(root)
        self._viewer.update(self._cursor_image.original)
        self._refresh_ui_state()

        self._root = root
        self._hotkeys_enabled = self._try_enable_hotkeys()
        logger.info("Hotkeys enabled: %s", self._hotkeys_enabled)
        logger.info("Capture backend: %s", self._capture_backend.backend_name)
        logger.info("Runtime config: %s", self._runtime_config.metadata())
        self._ensure_audio_monitor()
        if not self._hotkeys_enabled and sys.platform == "darwin":
            messagebox.showwarning(
                "Enable Accessibility Permissions",
                "Global hotkeys (F7/F8/F9/F10/F12) are disabled because this process "
                "is not trusted "
                "for "
                "input event monitoring.\n\n"
                "Fix: System Settings → Privacy & Security → Accessibility and Input Monitoring → "
                "enable your Terminal/IDE (the app you used to launch AutoAngler), then restart it."
                "\n\n"
                "You can still use the menu bar.",
            )

        self._bootstrap_idle_preview()
        self._tick()
        root.mainloop()

    @staticmethod
    def _build_indicator(parent, *, label: str):
        import tkinter as tk
        from tkinter import ttk

        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, 12))
        dot = tk.Canvas(frame, width=12, height=12, highlightthickness=0)
        dot.create_oval(2, 2, 10, 10, fill="#555555", outline="")
        dot.pack(side="left")
        ttk.Label(frame, text=label).pack(side="left", padx=(4, 0))
        return dot

    def _build_menu(self, root):
        import tkinter as tk

        menu = tk.Menu(root)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Exit", accelerator="Cmd+Q", command=self._quit)
        menu.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(
            label="Always On Top",
            variable=self._topmost_var,
            command=self._toggle_topmost,
        )
        view_menu.add_command(
            label="Debug Window",
            accelerator="F10",
            command=self._toggle_debug_window,
        )
        menu.add_cascade(label="View", menu=view_menu)
        return menu

    def _build_debug_window(self, root) -> None:
        import tkinter as tk
        from tkinter import ttk

        from autoangler.image_viewer_tk import ImageViewerTk

        window = tk.Toplevel(root)
        window.title("MC AutoAngler Debug")
        window.attributes("-topmost", self._topmost_enabled)
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

        container = ttk.Frame(window, padding=8)
        container.pack(fill="both", expand=True)

        self._debug_viewer = ImageViewerTk(dual=True)
        self._debug_viewer.frame(container).pack(fill="both", expand=True)

        ttk.Label(
            container,
            textvariable=self._debug_var,
            justify="left",
            font="TkFixedFont",
        ).pack(anchor="w", pady=(8, 0))

        self._debug_window = window
        window.withdraw()

    def _set_indicator_color(self, canvas: Any | None, color: str) -> None:
        if canvas is None:
            return
        try:
            canvas.itemconfigure(1, fill=color)
        except Exception:
            return

    def _refresh_ui_state(self) -> None:
        now = monotonic()
        if self._summary_var is not None:
            self._summary_var.set(
                main_window_summary_text(
                    fps=self._last_effective_fps,
                    tick_ms=self._last_tick_duration_ms,
                )
            )
        if self._catch_var is not None:
            self._catch_var.set(cast_ratio_text(bites=self._catch_count, casts=self._cast_count))

        record_color = "#cc2222" if self._recording_enabled and int(now * 2) % 2 == 0 else "#555555"
        fishing_color = "#1f8f3a" if self._is_fishing else "#555555"
        bite_color = "#d18b00" if (now - self._last_bite_indicator_at) < 1.0 else "#555555"

        self._set_indicator_color(self._recording_dot, record_color)
        self._set_indicator_color(self._fishing_dot, fishing_color)
        self._set_indicator_color(self._bite_dot, bite_color)

        if self._viewer is not None:
            self._viewer.set_border(self._preview_border_color())
        if self._debug_var is not None:
            self._debug_var.set(self._debug_stats_text())

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

    def _invalidate_vision_epoch(self) -> None:
        self._vision_epoch += 1
        self._last_applied_vision_seq = 0
        self._last_vision_completed_at = None
        self._last_vision_age_ms = 0.0
        self._last_vision_submit_at = 0.0

    def _bootstrap_idle_preview(self) -> None:
        self._refresh_preview_context()

    def _refresh_preview_context(self) -> bool:
        if not self._locate_minecraft_window():
            return False
        self._seed_default_guide_boxes()
        return True

    def _seed_default_guide_boxes(self) -> None:
        if self._minecraft_window is None or self._fishing_roi is None:
            return
        x1, y1, x2, y2 = window_relative_box(self._fishing_roi, self._minecraft_window)
        roi_frame = np.zeros((max(1, y2 - y1), max(1, x2 - x1)), dtype=np.uint8)
        self._tracking_box = self._default_tracking_box(roi_frame)
        self._detection_box = self._default_detection_box(roi_frame)
        self._line_candidate = None
        self._line_pixels = 0
        self._bite_detected = False
        self._rod_in_hand = False
        self._line_watcher.reset()
        self._preview_state = "neutral"

    def _vision_mode(self) -> str:
        return "fishing" if self._is_fishing else "idle_preview"

    def _vision_capture_interval_s(self) -> float:
        if self._vision_mode() == "idle_preview":
            return IDLE_CAPTURE_INTERVAL_S
        return self._max_capture_interval_s()

    def _preview_border_color(self) -> str:
        if self._preview_state == "valid":
            return "#1f8f3a"
        if self._preview_state == "invalid":
            return "#8c1d18"
        return "#68727c"

    def _should_write_profile_row(self) -> bool:
        return self._is_fishing or self._recording_enabled

    @staticmethod
    def _max_capture_interval_s() -> float:
        raw_value = os.environ.get("AUTOANGLER_MAX_CAPTURE_FPS", "10").strip()
        try:
            fps = float(raw_value)
        except ValueError:
            fps = 10.0
        if fps <= 0:
            fps = 10.0
        return 1.0 / fps

    def _ensure_vision_worker(self) -> VisionWorker:
        if self._vision_worker is None:
            self._vision_worker = VisionWorker()
        return self._vision_worker

    def _ensure_recording_worker(self) -> RecordingWorker:
        if self._recording_worker is None:
            log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
            self._recording_worker = RecordingWorker(
                log_path=Path(log_path) if log_path else None,
            )
        return self._recording_worker

    def _close_recording_worker(self) -> None:
        if self._recording_worker is None:
            return
        self._recording_worker.close()
        for event in self._recording_worker.poll_events():
            self._handle_recording_event(event)
        self._recording_worker = None
        self._record_queue_depth = 0

    def _close_vision_worker(self) -> None:
        if self._vision_worker is None:
            return
        self._vision_worker.close()
        self._vision_worker = None

    def _drain_recording_events(self) -> None:
        worker = self._recording_worker
        if worker is None:
            return
        self._record_queue_depth = worker.queue_depth
        self._record_dropped_frames = worker.dropped_frames
        for event in worker.poll_events():
            self._handle_recording_event(event)

    def _handle_recording_event(self, event: RecordingEvent) -> None:
        if event.kind == "screenshot_saved" and event.path is not None:
            self._last_saved_capture_name = event.path.name
        elif event.kind == "mark_saved" and event.path is not None:
            self._last_mark_clip_name = event.path.name
        self._record_queue_depth = event.queue_depth

    def _toggle_fishing(self) -> None:
        if self._is_fishing:
            self._stop(source="button")
        else:
            self._start()

    def _toggle_fishing_hotkey(self) -> None:
        if self._is_fishing:
            self._stop(source="hotkey_f12")
        else:
            self._start_hotkey()

    def _toggle_topmost(self) -> None:
        if self._topmost_var is not None and hasattr(self._topmost_var, "get"):
            self._topmost_enabled = bool(self._topmost_var.get())
        else:
            self._topmost_enabled = not self._topmost_enabled
        if self._root is not None:
            self._root.attributes("-topmost", self._topmost_enabled)
        if self._debug_window is not None:
            try:
                self._debug_window.attributes("-topmost", self._topmost_enabled)
            except Exception:
                pass
        if self._topmost_var is not None and hasattr(self._topmost_var, "set"):
            self._topmost_var.set(self._topmost_enabled)

    def _toggle_auto_strafe(self) -> None:
        if self._auto_strafe_var is not None and hasattr(self._auto_strafe_var, "get"):
            self._auto_strafe_enabled = bool(self._auto_strafe_var.get())
        else:
            self._auto_strafe_enabled = not self._auto_strafe_enabled
        if self._auto_strafe_var is not None and hasattr(self._auto_strafe_var, "set"):
            self._auto_strafe_var.set(self._auto_strafe_enabled)

    def _toggle_debug_window(self) -> None:
        window = self._debug_window
        if window is None:
            return
        try:
            visible = bool(window.winfo_viewable())
        except Exception:
            visible = False
        if visible:
            window.withdraw()
        else:
            window.deiconify()

    def _sync_line_state_indicator(self) -> None:
        if self._line_state_var is not None:
            self._line_state_var.set(line_state_text(is_line_out=self._is_line_out))

    def _toggle_recording(self) -> None:
        self._recording_enabled = not self._recording_enabled
        if self._recording_enabled:
            self._last_recording_capture_at = 0.0
            logger.info("Recording enabled")
        else:
            self._close_recording_worker()
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
            self._debug_var.set(self._debug_stats_text())
        self._refresh_ui_state()

    def _start(self) -> None:
        self._begin_start(delay_ms=5000)

    def _start_hotkey(self) -> None:
        self._begin_start(delay_ms=0)

    def _begin_start(self, *, delay_ms: int) -> None:
        if self._root is None:
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
        self._catch_count = 0
        self._cast_count = 0
        self._last_bite_indicator_at = 0.0
        self._line_watcher.reset()
        self._reset_movement_state()
        self._invalidate_vision_epoch()

        if self._button is not None:
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

    def _stop(self, *, source: str = "system") -> None:
        if self._root is None and self._button is None:
            return

        logger.info("Stop fishing requested")
        self._is_fishing = False
        self._is_line_out = False
        self._start_clock = None
        self._bite_detected = False
        self._line_watcher.reset()
        self._reset_movement_state()
        self._invalidate_vision_epoch()

        if not self._exiting:
            if self._button is not None:
                self._button.configure(text="Start Fishing")
            if self._status_var is not None:
                self._status_var.set("Stopped")
        self._sync_line_state_indicator()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="stop", source=source)
        self._close_recording_worker()

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
        self._preview_state = "neutral"
        self._line_watcher.reset()
        self._invalidate_vision_epoch()
        logger.info("Using Minecraft window '%s' at %s", window.title, window)
        logger.info("Fishing ROI set to %s", self._fishing_roi)
        if self._status_var is not None:
            self._status_var.set(f"Window: {window.title or '<untitled>'}")
        return True

    @staticmethod
    def _window_geometry_signature(window: Any) -> tuple[Any, ...]:
        return (
            getattr(window, "title", ""),
            getattr(window, "left", 0),
            getattr(window, "top", 0),
            getattr(window, "width", 0),
            getattr(window, "height", 0),
        )

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
        return self._refresh_preview_context()

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
        left = anchor_x - (width // 2)
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

    def _build_main_preview_frame(
        self,
        window_frame: np.ndarray,
        roi_box: tuple[int, int, int, int],
        roi_frame: np.ndarray,
        *,
        preview_state: str | None = None,
    ) -> np.ndarray:
        del window_frame, roi_box
        annotated = roi_frame.copy()
        tracking_box, _tracking_frame = self._tracking_frame(roi_frame)
        detection_box, _detection_frame = self._detection_frame(roi_frame)

        x1, y1, x2, y2 = tracking_box
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color=0, thickness=GUIDE_STROKE_PX)

        dx1, dy1, dx2, dy2 = detection_box
        cv2.rectangle(annotated, (dx1, dy1), (dx2, dy2), color=64, thickness=GUIDE_STROKE_PX)

        if self._line_candidate is not None:
            lx1, ly1, lx2, ly2 = self._line_candidate.bbox
            cv2.rectangle(annotated, (lx1, ly1), (lx2, ly2), color=96, thickness=1)
            cv2.circle(annotated, self._line_candidate.center, radius=2, color=96, thickness=-1)

        border_state = preview_state or self._preview_state
        if border_state not in {"neutral", "valid", "invalid"}:
            border_state = "valid" if self._main_preview_is_valid() else "invalid"
        border_color = 128 if border_state == "neutral" else 96 if border_state == "valid" else 0
        height, width = annotated.shape[:2]
        cv2.rectangle(annotated, (0, 0), (width - 1, height - 1), color=border_color, thickness=2)
        return annotated

    def _main_preview_is_valid(self) -> bool:
        if self._is_line_out:
            return self._detection_box is not None and self._line_pixels > 0
        return self._rod_in_hand

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
            self._debug_var.set(self._debug_stats_text())

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
            self._debug_var.set(self._debug_stats_text())
        return folder

    def _window_state_path(self) -> Path:
        return Path.home() / ".autoangler" / "window.json"

    def _load_window_geometry(self) -> str:
        try:
            data = json.loads(self._window_state_path().read_text())
        except Exception:
            return DEFAULT_WINDOW_GEOMETRY

        self._topmost_enabled = bool(data.get("topmost", True))

        position = str(data.get("position", "")).strip()
        if self._is_window_position(position):
            width, height = main_window_minsize()
            return f"{width}x{height}{position}"

        geometry = str(data.get("geometry", "")).strip()
        if self._is_window_geometry(geometry):
            return normalized_main_window_geometry(geometry)
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
        position = window_position_from_geometry(geometry)
        state_path.write_text(
            json.dumps(
                {
                    "geometry": geometry,
                    "position": position,
                    "topmost": self._topmost_enabled,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        logger.info("Saved window geometry %s to %s", geometry, state_path)
        return state_path

    @staticmethod
    def _is_window_geometry(geometry: str) -> bool:
        return re.fullmatch(r"\d+x\d+[+-]\d+[+-]\d+", geometry) is not None

    @staticmethod
    def _is_window_position(position: str) -> bool:
        return re.fullmatch(r"[+-]\d+[+-]\d+", position) is not None

    def _mark_bite(self) -> Path | None:
        now = monotonic()
        path = None
        if self._recording_enabled:
            path = self._append_trace_row(now=now, event="mark", source="manual")
        self._capture_mark_clip("mark", now=now)
        logger.info("Manual bite mark")
        if self._status_var is not None:
            self._status_var.set("Marked bite")
        if self._debug_var is not None:
            self._debug_var.set(self._debug_stats_text())
        return path

    def _manual_action(self) -> Path | None:
        now = monotonic()
        path = None
        if self._is_fishing and self._is_line_out:
            label = "hit" if self._bite_detected else "miss"
            if self._recording_enabled:
                path = self._append_trace_row(
                    now=now,
                    event="training_reel",
                    source="training",
                    training_label=label,
                )
            self._capture_mark_clip(f"training-{label}", now=now)
            self._reel_and_recast(source="training")
            status = f"Manual reel ({label})"
        else:
            if self._recording_enabled:
                path = self._append_trace_row(now=now, event="manual_cast", source="manual")
            self._capture_mark_clip("manual-cast", now=now)
            self._cast()
            status = "Manual cast"
        if self._status_var is not None:
            self._status_var.set(status)
        if self._debug_var is not None:
            self._debug_var.set(self._debug_stats_text())
        return path

    def _training_mark_and_reel(self) -> Path | None:
        now = monotonic()
        label = "hit" if self._bite_detected else "miss"
        path = None
        if self._recording_enabled:
            path = self._append_trace_row(
                now=now,
                event="training_reel",
                source="training",
                training_label=label,
            )
        self._capture_mark_clip(f"training-{label}", now=now)
        if self._is_fishing and self._is_line_out:
            self._reel_and_recast(source="training")
            status = f"Training reel ({label})"
        else:
            status = f"Training mark ({label})"
        if self._status_var is not None:
            self._status_var.set(status)
        if self._debug_var is not None:
            self._debug_var.set(self._debug_stats_text())
        return path

    def _save_screenshot(self, label: str, *, image: np.ndarray | None = None) -> Path:
        if image is None:
            image = self._cursor_image.original
        filename = self._next_screenshot_path(label)
        self._ensure_recording_worker().enqueue_screenshot(path=filename, image=image)
        self._last_saved_capture_name = filename.name
        logger.info("Queued screenshot to %s", filename)
        self._screenshot_index += 1
        return filename

    def _close_session_recorder(self) -> None:
        self._close_recording_worker()

    def _next_screenshot_path(self, label: str) -> Path:
        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            return build_session_capture_path(
                Path(log_path),
                f"{label}-{self._screenshot_index:02d}",
            )
        return Path.home() / ".autoangler" / f"{label}-{self._screenshot_index:02d}.png"

    def _append_trace_row(
        self,
        *,
        now: float,
        event: str,
        source: str = "system",
        training_label: str = "",
        scheduled_delay_ms: int | None = None,
        audio_hint_rms: float | None = None,
        audio_hint_peak: float | None = None,
        strafe_direction: str = "",
        strafe_duration_ms: int | None = None,
        strafe_offset_steps: int | None = None,
        mouse_dx_px: int | None = None,
        mouse_dy_px: int | None = None,
        mouse_offset_x_px: int | None = None,
        mouse_offset_y_px: int | None = None,
    ) -> Path:
        log_path = os.environ.get("AUTOANGLER_SESSION_LOG", "").strip()
        if log_path:
            trace_path = build_session_trace_path(Path(log_path))
        else:
            trace_path = Path.home() / ".autoangler" / "trace.csv"

        metadata = self._runtime_config.metadata()
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
                    "cast_settle_min_ms",
                    "cast_settle_max_ms",
                    "recast_min_ms",
                    "recast_max_ms",
                    "audio_hints_enabled",
                    "auto_strafe_enabled",
                    "scheduled_delay_ms",
                    "audio_hint_rms",
                    "audio_hint_peak",
                    "strafe_direction",
                    "strafe_duration_ms",
                    "strafe_offset_steps",
                    "mouse_dx_px",
                    "mouse_dy_px",
                    "mouse_offset_x_px",
                    "mouse_offset_y_px",
                    "source",
                    "training_label",
                    "rod_in_hand",
                    "catch_count",
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
                    "cast_settle_min_ms": metadata["cast_settle_min_ms"],
                    "cast_settle_max_ms": metadata["cast_settle_max_ms"],
                    "recast_min_ms": metadata["recast_min_ms"],
                    "recast_max_ms": metadata["recast_max_ms"],
                    "audio_hints_enabled": metadata["audio_hints_enabled"],
                    "auto_strafe_enabled": int(self._auto_strafe_enabled),
                    "scheduled_delay_ms": "" if scheduled_delay_ms is None else scheduled_delay_ms,
                    "audio_hint_rms": (
                        "" if audio_hint_rms is None else f"{audio_hint_rms:.4f}"
                    ),
                    "audio_hint_peak": (
                        "" if audio_hint_peak is None else f"{audio_hint_peak:.4f}"
                    ),
                    "strafe_direction": strafe_direction,
                    "strafe_duration_ms": (
                        "" if strafe_duration_ms is None else strafe_duration_ms
                    ),
                    "strafe_offset_steps": (
                        "" if strafe_offset_steps is None else strafe_offset_steps
                    ),
                    "mouse_dx_px": "" if mouse_dx_px is None else mouse_dx_px,
                    "mouse_dy_px": "" if mouse_dy_px is None else mouse_dy_px,
                    "mouse_offset_x_px": (
                        "" if mouse_offset_x_px is None else mouse_offset_x_px
                    ),
                    "mouse_offset_y_px": (
                        "" if mouse_offset_y_px is None else mouse_offset_y_px
                    ),
                    "source": source,
                    "training_label": training_label,
                    "rod_in_hand": int(self._rod_in_hand),
                    "catch_count": self._catch_count,
                }
            )

        self._last_trace_name = trace_path.name
        event_parts = [
            f"source={source}",
            f"is_fishing={int(self._is_fishing)}",
            f"is_line_out={int(self._is_line_out)}",
            f"line_pixels={self._line_pixels}",
            f"trigger_pixels={self._line_watcher.trigger_pixels}",
            f"weak_frames={self._line_watcher.weak_frames}",
            f"bite_detected={int(self._bite_detected)}",
            f"rod_in_hand={int(self._rod_in_hand)}",
            f"catch_count={self._catch_count}",
        ]
        if scheduled_delay_ms is not None:
            event_parts.append(f"scheduled_delay_ms={scheduled_delay_ms}")
        if audio_hint_rms is not None:
            event_parts.append(f"audio_hint_rms={audio_hint_rms:.4f}")
        if audio_hint_peak is not None:
            event_parts.append(f"audio_hint_peak={audio_hint_peak:.4f}")
        if strafe_direction:
            event_parts.append(f"strafe_direction={strafe_direction}")
        if strafe_duration_ms is not None:
            event_parts.append(f"strafe_duration_ms={strafe_duration_ms}")
        if strafe_offset_steps is not None:
            event_parts.append(f"strafe_offset_steps={strafe_offset_steps}")
        if mouse_dx_px is not None:
            event_parts.append(f"mouse_dx_px={mouse_dx_px}")
        if mouse_dy_px is not None:
            event_parts.append(f"mouse_dy_px={mouse_dy_px}")
        if mouse_offset_x_px is not None:
            event_parts.append(f"mouse_offset_x_px={mouse_offset_x_px}")
        if mouse_offset_y_px is not None:
            event_parts.append(f"mouse_offset_y_px={mouse_offset_y_px}")
        if training_label:
            event_parts.append(f"training_label={training_label}")
        event_message = "EVENT %s %s"
        if event == "tick":
            logger.debug(event_message, event, " ".join(event_parts))
        else:
            logger.info(event_message, event, " ".join(event_parts))
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

        metadata = self._runtime_config.metadata()
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not profile_path.exists() or profile_path.stat().st_size == 0
        with profile_path.open("a", encoding="utf-8", newline="") as handle:
            writer = DictWriter(
                handle,
                fieldnames=[
                    "time_s",
                    "cast_settle_min_ms",
                    "cast_settle_max_ms",
                    "recast_min_ms",
                    "recast_max_ms",
                    "audio_hints_enabled",
                    "auto_strafe_enabled",
                    "is_fishing",
                    "is_line_out",
                    "total_ms",
                    "capture_ms",
                    "detect_ms",
                    "preview_ms",
                    "record_ms",
                    "vision_age_ms",
                    "vision_dropped_frames",
                    "record_queue_depth",
                    "record_dropped_frames",
                    "line_pixels",
                    "trigger_pixels",
                ],
            )
            if write_header:
                writer.writeheader()
            writer.writerow(
                {
                    "time_s": f"{now:.3f}",
                    "cast_settle_min_ms": metadata["cast_settle_min_ms"],
                    "cast_settle_max_ms": metadata["cast_settle_max_ms"],
                    "recast_min_ms": metadata["recast_min_ms"],
                    "recast_max_ms": metadata["recast_max_ms"],
                    "audio_hints_enabled": metadata["audio_hints_enabled"],
                    "auto_strafe_enabled": int(self._auto_strafe_enabled),
                    "is_fishing": int(self._is_fishing),
                    "is_line_out": int(self._is_line_out),
                    "total_ms": f"{total_ms:.1f}",
                    "capture_ms": f"{capture_ms:.1f}",
                    "detect_ms": f"{detect_ms:.1f}",
                    "preview_ms": f"{preview_ms:.1f}",
                    "record_ms": f"{record_ms:.1f}",
                    "vision_age_ms": f"{self._last_vision_age_ms:.1f}",
                    "vision_dropped_frames": self._vision_dropped_frames,
                    "record_queue_depth": self._record_queue_depth,
                    "record_dropped_frames": self._record_dropped_frames,
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

        if (
            self._latest_window_frame is not None
            and self._latest_debug_composite is not None
        ):
            self._ensure_recording_worker().enqueue_frame(
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
            self._recording_worker.window_video_path.name
            if self._recording_worker is not None and self._recording_worker.window_video_path
            else "-"
        )
        debug_video = (
            self._recording_worker.debug_video_path.name
            if self._recording_worker is not None and self._recording_worker.debug_video_path
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

    def _debug_stats_text(self) -> str:
        return (
            "Status\n"
            f"recording: {'on' if self._recording_enabled else 'off'}\n"
            f"is_fishing: {int(self._is_fishing)}\n"
            f"is_line_out: {int(self._is_line_out)}\n"
            f"rod_in_hand: {int(self._rod_in_hand)}\n"
            f"catch_count: {self._catch_count}\n\n"
            f"cast_count: {self._cast_count}\n\n"
            "Detection\n"
            f"roi: {self._fishing_roi}\n"
            f"track: {self._tracking_box}\n"
            f"detect: {self._detection_box}\n"
            f"line_pixels: {self._line_pixels}\n\n"
            "Recording\n"
            f"last_trace: {self._last_trace_name or '-'}\n"
            f"last_mark: {self._last_mark_clip_name or '-'}\n"
            f"last_capture: {self._last_saved_capture_name or '-'}\n\n"
            "Performance\n"
            f"{self._profile_summary_text()}"
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
            f"vage:{self._last_vision_age_ms:.1f}ms "
            f"vdrop:{self._vision_dropped_frames} "
            f"rqueue:{self._record_queue_depth} "
            f"rdrop:{self._record_dropped_frames} "
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
        self._ensure_recording_worker().enqueue_mark(label=label, now=now)
        return None

    def _set_rod_in_hand(self, value: bool) -> None:
        if value == self._rod_in_hand:
            return
        self._rod_in_hand = value
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="rod_state", source="system")

    def _update_rod_state(self, window_frame: np.ndarray) -> None:
        if self._minecraft_window is None:
            return
        detected = self._rod_detector.detect(window_frame, window=self._minecraft_window)
        self._set_rod_in_hand(detected)

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

    def _choose_delay_ms(self, delay_range: DelayRange) -> int:
        return delay_range.choose(rng=self._random)

    def _reset_movement_state(self) -> None:
        self._movement_state = MovementState()

    def _cast(self) -> None:
        if self._root is None:
            return

        logger.info("Cast")
        self._bite_detected = False
        self._cast_count += 1
        self._line_watcher.reset()
        self._use_rod()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="cast")
        cast_delay_ms = self._choose_delay_ms(self._runtime_config.cast_settle)
        if self._recording_enabled:
            self._append_trace_row(
                now=monotonic(),
                event="line_out_scheduled",
                scheduled_delay_ms=cast_delay_ms,
            )
        self._root.after(cast_delay_ms, self._mark_line_out)

    def _mark_line_out(self) -> None:
        if self._is_fishing:
            self._is_line_out = True
            self._sync_line_state_indicator()
            if self._recording_enabled:
                self._append_trace_row(now=monotonic(), event="line_out")

    def _reel(self, source: str = "system") -> None:
        logger.info("Reel")
        self._use_rod()
        self._is_line_out = False
        self._sync_line_state_indicator()
        if self._recording_enabled:
            self._append_trace_row(now=monotonic(), event="reel", source=source)

    def _reel_and_recast(self, source: str = "system") -> None:
        self._reel(source=source)
        if self._root is None:
            self._cast()
            return

        recast_delay_ms = self._choose_delay_ms(self._runtime_config.recast)
        recast_delay_ms = self._maybe_auto_strafe(total_delay_ms=recast_delay_ms)
        if self._recording_enabled:
            self._append_trace_row(
                now=monotonic(),
                event="recast_scheduled",
                source=source,
                scheduled_delay_ms=recast_delay_ms,
            )
        self._root.after(recast_delay_ms, self._cast)

    def _choose_next_strafe_offset(self, current: int) -> int:
        if current >= AUTO_STRAFE_MAX_OFFSET_STEPS:
            return current - 1
        if current <= -AUTO_STRAFE_MAX_OFFSET_STEPS:
            return current + 1
        if current == 0:
            return self._random.choice([-1, 1])

        toward_zero = current - 1 if current > 0 else current + 1
        away_from_zero = current + 1 if current > 0 else current - 1
        if self._random.random() < 0.7:
            return toward_zero
        return max(
            -AUTO_STRAFE_MAX_OFFSET_STEPS,
            min(AUTO_STRAFE_MAX_OFFSET_STEPS, away_from_zero),
        )

    def _choose_next_mouse_offset(
        self,
        current: int,
        *,
        step_px: int,
        max_px: int,
    ) -> int:
        if current >= max_px:
            return current - step_px
        if current <= -max_px:
            return current + step_px
        if current == 0:
            return self._random.choice([-step_px, step_px])

        toward_zero = current - step_px if current > 0 else current + step_px
        away_from_zero = current + step_px if current > 0 else current - step_px
        if self._random.random() < 0.7:
            return toward_zero
        return max(-max_px, min(max_px, away_from_zero))

    @staticmethod
    def _scaled_mouse_delta(delta_px: int, *, remaining_delay_ms: int) -> int:
        if delta_px == 0:
            return 0
        if remaining_delay_ms <= 0:
            return 0
        if remaining_delay_ms >= AUTO_MOUSE_DRIFT_STEP_DELAY_MS:
            return delta_px

        scaled = int(abs(delta_px) * remaining_delay_ms / AUTO_MOUSE_DRIFT_STEP_DELAY_MS)
        if scaled <= 0:
            return 0
        return scaled if delta_px > 0 else -scaled

    def _maybe_auto_strafe(self, *, total_delay_ms: int) -> int:
        if not self._auto_strafe_enabled:
            return total_delay_ms

        movement = self._movement_state
        target_strafe_offset = self._choose_next_strafe_offset(
            movement.current_strafe_offset_steps
        )
        strafe_delta_steps = target_strafe_offset - movement.current_strafe_offset_steps
        requested_strafe_duration_ms = abs(strafe_delta_steps) * AUTO_STRAFE_STEP_MS
        strafe_duration_ms = min(total_delay_ms, requested_strafe_duration_ms)
        strafe_direction = ""
        if strafe_delta_steps != 0 and strafe_duration_ms > 0:
            strafe_direction = "left" if strafe_delta_steps < 0 else "right"
            key = "a" if strafe_direction == "left" else "d"
            pyautogui.keyDown(key)
            try:
                sleep(strafe_duration_ms / 1000)
            finally:
                pyautogui.keyUp(key)
            if strafe_duration_ms >= requested_strafe_duration_ms:
                movement.current_strafe_offset_steps = target_strafe_offset

        remaining_delay_ms = max(0, total_delay_ms - strafe_duration_ms)

        target_mouse_offset_x = self._choose_next_mouse_offset(
            movement.current_mouse_offset_x_px,
            step_px=AUTO_MOUSE_DRIFT_STEP_X_PX,
            max_px=AUTO_MOUSE_DRIFT_MAX_X_PX,
        )
        target_mouse_offset_y = self._choose_next_mouse_offset(
            movement.current_mouse_offset_y_px,
            step_px=AUTO_MOUSE_DRIFT_STEP_Y_PX,
            max_px=AUTO_MOUSE_DRIFT_MAX_Y_PX,
        )
        desired_mouse_dx = target_mouse_offset_x - movement.current_mouse_offset_x_px
        desired_mouse_dy = target_mouse_offset_y - movement.current_mouse_offset_y_px
        mouse_dx = self._scaled_mouse_delta(
            desired_mouse_dx,
            remaining_delay_ms=remaining_delay_ms,
        )
        mouse_dy = self._scaled_mouse_delta(
            desired_mouse_dy,
            remaining_delay_ms=remaining_delay_ms,
        )
        if mouse_dx != 0 or mouse_dy != 0:
            pyautogui.moveRel(mouse_dx, mouse_dy, duration=0)
            movement.current_mouse_offset_x_px += mouse_dx
            movement.current_mouse_offset_y_px += mouse_dy

        if self._recording_enabled:
            self._append_trace_row(
                now=monotonic(),
                event="strafe",
                source="auto_strafe",
                strafe_direction=strafe_direction,
                strafe_duration_ms=strafe_duration_ms,
                strafe_offset_steps=movement.current_strafe_offset_steps,
                mouse_dx_px=mouse_dx,
                mouse_dy_px=mouse_dy,
                mouse_offset_x_px=movement.current_mouse_offset_x_px,
                mouse_offset_y_px=movement.current_mouse_offset_y_px,
            )
        return remaining_delay_ms

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

    def _maybe_refresh_tracking_context(self, *, now: float) -> None:
        if now - self._last_context_refresh_at < 0.5:
            return
        self._last_context_refresh_at = now

        if self._minecraft_window is None:
            if self._should_capture_preview():
                self._refresh_preview_context()
            return

        latest = selected_minecraft_window()
        if latest is None:
            return
        if self._window_geometry_signature(latest) != self._window_geometry_signature(
            self._minecraft_window
        ):
            self._refresh_preview_context()

    def _submit_vision_request(self, *, now: float) -> None:
        min_interval_s = self._vision_capture_interval_s()
        if self._last_vision_submit_at and (now - self._last_vision_submit_at) < min_interval_s:
            return
        self._last_vision_submit_at = now
        self._next_vision_seq += 1
        request = VisionRequest(
            epoch=self._vision_epoch,
            seq=self._next_vision_seq,
            submitted_at=now,
            minecraft_window=self._minecraft_window,
            fishing_roi=self._fishing_roi,
            tracking_box=self._tracking_box,
            detection_box=self._detection_box,
            is_fishing=self._is_fishing,
            is_line_out=self._is_line_out,
            mode=self._vision_mode(),
        )
        worker = self._ensure_vision_worker()
        worker.submit(request)
        self._vision_dropped_frames = worker.dropped_frames

    def _drain_vision_results(self) -> None:
        worker = self._vision_worker
        if worker is None:
            return
        for result in worker.poll_results():
            self._apply_vision_result(result)
        self._vision_dropped_frames = worker.dropped_frames
        if self._last_vision_completed_at is not None:
            self._last_vision_age_ms = round(
                (monotonic() - self._last_vision_completed_at) * 1000,
                1,
            )

    def _apply_vision_result(self, result: VisionResult) -> bool:
        if result.epoch != self._vision_epoch:
            return False
        if result.seq <= self._last_applied_vision_seq:
            return False

        self._last_applied_vision_seq = result.seq
        self._last_vision_completed_at = result.completed_at
        self._last_vision_age_ms = round((monotonic() - result.completed_at) * 1000, 1)
        self._last_capture_duration_ms = result.capture_ms
        self._last_detect_duration_ms = result.detect_ms

        if result.capture_error is not None:
            self._consecutive_capture_failures += 1
            self._last_capture_error = result.capture_error
            self._preview_state = "invalid"
            if self._consecutive_capture_failures >= 3:
                self._minecraft_window = None
                self._fishing_roi = None
                self._tracking_box = None
                self._detection_box = None
                self._invalidate_vision_epoch()
            return False

        self._consecutive_capture_failures = 0
        self._last_capture_error = None
        self._latest_window_frame = result.window_frame.copy()
        self._latest_debug_composite = result.debug_composite.copy()
        self._line_candidate = result.line_candidate
        self._line_pixels = result.line_pixels
        self._cursor_image = result.tracking_preview
        self._preview_state = result.preview_state
        self._set_rod_in_hand(result.rod_in_hand)

        if self._tracking_box is None and result.suggested_tracking_box is not None:
            self._tracking_box = result.suggested_tracking_box
        if self._detection_box is None and result.suggested_detection_box is not None:
            self._detection_box = result.suggested_detection_box

        previous_bite_detected = self._bite_detected
        self._bite_detected = self._line_watcher.observe(
            self._line_pixels,
            active=self._is_fishing and self._is_line_out,
        )
        if self._bite_detected and not previous_bite_detected:
            self._record_detection_event(event="bite_detected", source="vision")

        preview_start = monotonic()
        if self._viewer is not None:
            self._viewer.update(result.main_preview_frame)
        if self._debug_viewer is not None:
            self._debug_viewer.update(
                result.tracking_preview.original,
                result.tracking_preview.computer,
            )
        self._last_preview_duration_ms = round((monotonic() - preview_start) * 1000, 1)

        if self._is_fish_on():
            self._catch_count += 1
            self._last_bite_indicator_at = monotonic()
            self._reel_and_recast(source="vision")
        return True

    def _tick(self) -> None:
        if self._root is None:
            return

        start_time = monotonic()
        record_duration_ms = 0.0
        self._drain_recording_events()
        self._drain_vision_results()

        if self._should_capture_preview():
            self._maybe_refresh_tracking_context(now=monotonic())
            self._submit_vision_request(now=monotonic())
            tick_now = monotonic()
            record_start = monotonic()
            self._maybe_record_frame(now=tick_now)
            record_duration_ms = round((monotonic() - record_start) * 1000, 1)
            if self._recording_enabled and self._is_fishing:
                self._append_trace_row(now=tick_now, event="tick")

        self._drain_audio_hints(now=monotonic())

        if self._is_fish_on():
            self._catch_count += 1
            self._last_bite_indicator_at = monotonic()
            self._reel_and_recast(source="vision")

        duration_ms = round((monotonic() - start_time) * 1000, 1)
        if self._should_capture_preview() and self._should_write_profile_row():
            self._append_profile_row(
                now=monotonic(),
                total_ms=duration_ms,
                capture_ms=self._last_capture_duration_ms,
                detect_ms=self._last_detect_duration_ms,
                preview_ms=self._last_preview_duration_ms,
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
                    capture_ms=self._last_capture_duration_ms,
                    detect_ms=self._last_detect_duration_ms,
                    preview_ms=self._last_preview_duration_ms,
                    record_ms=record_duration_ms,
                )
            )
            summary = self._profiler.summary()
            self._last_tick_duration_ms = duration_ms
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
                self._debug_var.set(self._debug_stats_text())
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
            self._debug_var.set(self._debug_stats_text())

        self._sync_line_state_indicator()
        self._refresh_ui_state()

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
                self._viewer.update(self._cursor_image.original)
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
        self._update_rod_state(window_frame)
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
        previous_bite_detected = self._bite_detected
        self._bite_detected = self._line_watcher.observe(
            self._line_pixels,
            active=self._is_fishing and self._is_line_out,
        )
        if self._bite_detected and not previous_bite_detected:
            self._record_detection_event(event="bite_detected", source="vision")
        detect_duration_ms = round((monotonic() - detect_start) * 1000, 1)

        preview_start = monotonic()
        main_preview = self._build_main_preview_frame(window_frame, roi_box, roi_frame)
        self._latest_window_frame = window_frame.copy()
        self._latest_debug_composite = self._build_debug_composite()
        if auto_calibrated and self._line_candidate is None:
            self._maybe_save_debug_screenshot("line-miss", image=self._cursor_image.original)

        self._viewer.update(main_preview)
        if self._debug_viewer is not None:
            self._debug_viewer.update(self._cursor_image.original, self._cursor_image.computer)
        preview_duration_ms = round((monotonic() - preview_start) * 1000, 1)

        return capture_duration_ms, detect_duration_ms, preview_duration_ms

    def _ensure_audio_monitor(self) -> None:
        if self._audio_monitor_started or not self._runtime_config.audio_hints_enabled:
            return
        if self._audio_monitor is None:
            self._audio_monitor = AudioHintMonitor(title_hint="Minecraft")
        try:
            self._audio_monitor_started = bool(self._audio_monitor.start())
        except Exception as exc:
            logger.warning("Could not start audio hint monitor: %s", exc)
            self._audio_monitor_started = False

    def _drain_audio_hints(self, *, now: float) -> None:
        if self._audio_monitor is None:
            return
        for event in self._audio_monitor.poll():
            self._last_audio_hint = event
            self._last_bite_indicator_at = monotonic()
            logger.info(
                "Audio bite hint t=%.3f rms=%.4f peak=%.4f",
                event.timestamp,
                event.rms,
                event.peak,
            )
            self._record_detection_event(
                event="audio_hint",
                source="audio",
                now=now,
                audio_hint_rms=event.rms,
                audio_hint_peak=event.peak,
            )

    def _record_detection_event(
        self,
        *,
        event: str,
        source: str,
        now: float | None = None,
        audio_hint_rms: float | None = None,
        audio_hint_peak: float | None = None,
    ) -> None:
        if not self._recording_enabled:
            return
        self._append_trace_row(
            now=now if now is not None else monotonic(),
            event=event,
            source=source,
            audio_hint_rms=audio_hint_rms,
            audio_hint_peak=audio_hint_peak,
        )

    def _is_fish_on(self) -> bool:
        return self._is_fishing and self._is_line_out and self._bite_detected

    def _on_key_press(self, key) -> None:
        root = self._root
        if root is None:
            return

        if key == keyboard.Key.f7:
            logger.info("Hotkey pressed: f7")
            root.after(0, self._toggle_recording)
        elif key == keyboard.Key.f8:
            logger.info("Hotkey pressed: f8")
            root.after(0, self._manual_action)
        elif key == keyboard.Key.f12:
            logger.info("Hotkey pressed: f12")
            root.after(0, self._toggle_fishing_hotkey)
        elif key == keyboard.Key.f9:
            logger.info("Hotkey pressed: f9")
            root.after(0, self._refresh_tracking_context)
        elif key == keyboard.Key.f10:
            logger.info("Hotkey pressed: f10")
            root.after(0, self._toggle_debug_window)

    def _refresh_tracking_context(self) -> None:
        if not self._refresh_preview_context():
            return
        self._calibrate_line()

    def _quit(self) -> None:
        if self._exiting:
            return

        self._exiting = True
        self._save_window_geometry()
        self._stop(source="quit")
        try:
            self._keyboard_listener.stop()
        finally:
            self._close_session_recorder()
            self._close_vision_worker()
            if self._audio_monitor is not None:
                self._audio_monitor.close()
            self._capture_backend.close()
            if self._debug_window is not None:
                try:
                    self._debug_window.destroy()
                except Exception:
                    pass
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
