from __future__ import annotations

import logging
import sys
from time import monotonic, time
from typing import Any

import numpy as np
import pyautogui
from pynput import keyboard

from autoangler.cursor_camera import CursorCamera
from autoangler.cursor_locator import CursorLocator
from autoangler.screen import get_virtual_screen_bounds

# The default pause sometimes causes the cast to also retrieve
pyautogui.PAUSE = 0.01

MINECRAFT_TICKS_PER_MC_DAY = 24000
MINECRAFT_TICKS_PER_HOUR = MINECRAFT_TICKS_PER_MC_DAY / 24
MINECRAFT_IRL_MINUTES_PER_MC_DAY = 20
MINECRAFT_IRL_MINUTES_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_DAY / 24
MINECRAFT_IRL_SECONDS_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_HOUR * 60

logger = logging.getLogger(__name__)


def hotkey_hint_text(hotkeys_enabled: bool) -> str:
    suffix = "" if hotkeys_enabled else " (global hotkeys disabled)"
    return f"Hotkeys: F12 start | ESC stop | F10 exit{suffix}"


class AutoFishTkApp:
    def __init__(self) -> None:
        self._magnification: int = 10

        self._cursor_position: tuple[int, int] | None = None
        self._is_fishing = False
        self._is_line_out = False
        self._exiting = False

        self._loop_index: int = 0
        self._loop_durations_ms = np.zeros(100)
        self._tick_interval: int = 0
        self._current_clock: float = 0.0
        self._start_clock: float | None = None

        self._threshold = self._magnification * 22

        self._viewer: Any | None = None
        self._camera = CursorCamera(self._magnification)
        self._cursor_image = self._camera.blank()

        self._root: Any | None = None
        self._status_var: Any | None = None
        self._button: Any | None = None
        self._hotkey_hint_var: Any | None = None

        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._hotkeys_enabled = False
        self._relocating = False
        self._consecutive_capture_failures = 0
        self._last_capture_error: str | None = None

    def run(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, ttk

        from autoangler.image_viewer_tk import ImageViewerTk

        root = tk.Tk()
        root.title("MC AutoAngler")
        root.geometry("+300+0")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self._quit)

        container = ttk.Frame(root, padding=8)
        container.pack(fill="both", expand=True)

        self._viewer = ImageViewerTk()
        self._viewer.frame(container).pack(fill="both", expand=True)

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(0, 8))

        self._button = ttk.Button(controls, text="Start Fishing", command=self._toggle_fishing)
        self._button.pack(side="left")

        self._status_var = tk.StringVar(value="")
        ttk.Label(controls, textvariable=self._status_var).pack(side="left", padx=12)

        self._hotkey_hint_var = tk.StringVar(value=hotkey_hint_text(hotkeys_enabled=False))
        ttk.Label(container, textvariable=self._hotkey_hint_var).pack(anchor="w", pady=(0, 4))

        self._viewer.update(self._cursor_image)

        self._root = root
        self._hotkeys_enabled = self._try_enable_hotkeys()
        logger.info("Hotkeys enabled: %s", self._hotkeys_enabled)
        if self._hotkey_hint_var is not None:
            self._hotkey_hint_var.set(hotkey_hint_text(hotkeys_enabled=self._hotkeys_enabled))
        if not self._hotkeys_enabled and sys.platform == "darwin":
            messagebox.showwarning(
                "Enable Accessibility Permissions",
                "Global hotkeys (F12/ESC/F10) are disabled because this process isn't trusted for "
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

    def _start(self) -> None:
        if self._root is None or self._button is None:
            return

        logger.info("Start fishing requested")
        self._is_fishing = True
        self._cursor_position = None
        self._is_line_out = False
        self._start_clock = None
        self._tick_interval = 0
        self._current_clock = 0.0

        self._button.configure(text="Stop Fishing")

        # Give time to focus on Minecraft
        if self._status_var is not None:
            self._status_var.set("Starting in 5s... focus Minecraft")
        self._root.after(5000, self._locate_cursor_and_cast)

    def _stop(self) -> None:
        if self._button is None:
            return

        logger.info("Stop fishing requested")
        self._is_fishing = False
        self._cursor_position = None
        self._is_line_out = False
        self._start_clock = None

        if not self._exiting:
            self._button.configure(text="Start Fishing")
            if self._status_var is not None:
                self._status_var.set("Stopped")

    def _locate_cursor_and_cast(self) -> None:
        if not self._is_fishing:
            return

        if self._status_var is not None:
            self._status_var.set("Locating cursor...")
        self._locate_cursor()
        if self._cursor_position:
            logger.info("Cursor found at %s", self._cursor_position)
            self._cast()
        else:
            logger.warning("Could not locate cursor")
            if self._status_var is not None:
                self._status_var.set("Could not find cursor (retrying...)")
            if self._root is not None:
                self._root.after(2000, self._locate_cursor_and_cast)

    def _locate_cursor(self) -> None:
        cursor = CursorLocator()
        self._cursor_position = None
        for _ in range(5):
            self._cursor_position = cursor.locate()
            if self._cursor_position:
                return

        logger.debug(
            "Cursor locator failed. Try lowering AUTOANGLER_CURSOR_THRESHOLD (e.g. 0.6) or "
            "adjusting AUTOANGLER_CURSOR_SCALES (e.g. 1.0,2.0)."
        )

        if self._use_center_fallback():
            center = self._get_active_window_center() or self._get_virtual_screen_center()
            if center is not None:
                logger.warning("Falling back to screen/window center: %s", center)
                self._cursor_position = center

    @staticmethod
    def _use_center_fallback() -> bool:
        import os

        return os.environ.get("AUTOANGLER_CENTER_FALLBACK", "1").strip() not in {"0", "false", "no"}

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
        self._use_rod()
        self._root.after(3000, self._mark_line_out)

    def _mark_line_out(self) -> None:
        if self._is_fishing:
            self._is_line_out = True

    def _reel(self) -> None:
        logger.info("Reel")
        self._use_rod()
        self._is_line_out = False

    @staticmethod
    def _use_rod() -> None:
        pyautogui.rightClick()

    def _preview_target(self) -> tuple[int, int] | None:
        if self._cursor_position is not None:
            return self._cursor_position
        return self._get_active_window_center() or self._get_virtual_screen_center()

    def _tick(self) -> None:
        if self._root is None:
            return

        start_time = monotonic()

        self._update_image()

        if self._is_fish_on():
            self._reel()
            self._cast()

        if self._is_fishing:
            now = time()
            if self._start_clock is None:
                self._current_clock = now
                self._start_clock = now

            next_clock_position = self._current_clock + MINECRAFT_IRL_SECONDS_PER_MC_HOUR
            if now >= next_clock_position:
                self._tick_interval = (self._tick_interval + 1) % 23
                self._current_clock = next_clock_position

            duration_ms = round((monotonic() - start_time) * 1000, 1)

            self._loop_index = (self._loop_index + 1) % self._loop_durations_ms.size
            self._loop_durations_ms[self._loop_index] = duration_ms

            elapsed_s = int(now - self._start_clock)
            avg_ms = round(float(np.average(self._loop_durations_ms)), 1)
            status = (
                f"{self._cursor_image.black_pixel_count} < {self._threshold} "
                f"{elapsed_s}s {self._tick_interval}h {duration_ms}ms avg: {avg_ms}ms"
            )
            if self._status_var is not None:
                self._status_var.set(status)

        if not self._exiting:
            self._root.after(33, self._tick)

    def _update_image(self) -> None:
        if self._viewer is None:
            return
        target = self._preview_target()
        if target is None:
            return
        try:
            self._cursor_image = self._camera.capture(target)
            self._viewer.update(self._cursor_image)
            self._consecutive_capture_failures = 0
            self._last_capture_error = None
        except (OSError, ValueError):
            # Thrown when a capture fails; safe to skip a frame and recover.
            self._consecutive_capture_failures += 1
            self._last_capture_error = "capture failed"
            logger.debug(
                "Capture failed (%s consecutive). target=%s cursor_position=%s",
                self._consecutive_capture_failures,
                target,
                self._cursor_position,
            )
            if self._consecutive_capture_failures >= 3:
                self._cursor_position = None
                self._schedule_relocate_cursor()
            return

    def _schedule_relocate_cursor(self) -> None:
        root = self._root
        if root is None or self._relocating or not self._is_fishing:
            return

        logger.warning("Relocating cursor after repeated capture failures")
        self._relocating = True

        def do_relocate() -> None:
            self._relocating = False
            if not self._is_fishing:
                return
            if self._status_var is not None:
                self._status_var.set("Relocating cursor...")
            self._locate_cursor()

        root.after(1000, do_relocate)

    def _is_fish_on(self) -> bool:
        if not self._is_fishing or not self._is_line_out:
            return False
        return self._cursor_image.black_pixel_count <= self._threshold

    def _on_key_press(self, key) -> None:
        root = self._root
        if root is None:
            return

        if key == keyboard.Key.f12:
            root.after(0, self._start)
        elif key == keyboard.Key.esc:
            root.after(0, self._stop)
        elif key == keyboard.Key.f10:
            root.after(0, self._quit)

    def _quit(self) -> None:
        if self._exiting:
            return

        self._exiting = True
        self._stop()
        try:
            self._keyboard_listener.stop()
        finally:
            if self._root is not None:
                self._root.destroy()
