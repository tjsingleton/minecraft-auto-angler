"""Replace desktop boundaries while exercising the real coordinator and workers."""

from __future__ import annotations

import csv
import heapq
import json
import random
import threading
from collections import deque
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from queue import Queue

import cv2
import numpy as np

from autoangler import async_pipeline, capture_backend, cursor_camera, cursor_locator, gui_tk
from autoangler.audio_probe import AudioHintEvent
from autoangler.cursor_image import CursorImage
from autoangler.minecraft_window import WindowInfo
from autoangler.runtime_config import RuntimeConfig
from autoangler.screen import ScreenBounds


class VirtualRoot:
    def __init__(self) -> None:
        self.now = 100.0
        self.pending = []
        self.sequence = 0
        self.destroyed = False

    def after(self, delay_ms, callback):
        self.sequence += 1
        heapq.heappush(self.pending, (self.now + delay_ms / 1000, self.sequence, callback))
        return self.sequence

    def advance(self, milliseconds: int) -> None:
        target = self.now + milliseconds / 1000
        while self.pending and self.pending[0][0] <= target:
            due, _, callback = heapq.heappop(self.pending)
            self.now = due
            callback()
        self.now = max(target, self.now)

    def remove_callback(self, callback) -> None:
        self.pending = [entry for entry in self.pending if entry[2] != callback]
        heapq.heapify(self.pending)

    def geometry(self) -> str:
        return "384x328+300+0"

    def destroy(self) -> None:
        self.destroyed = True


class Value:
    def __init__(self, value="") -> None:
        self.value = value

    def set(self, value) -> None:
        self.value = value

    def get(self):
        return self.value


class Preview:
    def __init__(self) -> None:
        self.frame = None
        self.border = None
        self.thread_ids = []

    def update(self, frame, *_args) -> None:
        self.thread_ids.append(threading.get_ident())
        self.frame = (frame.original if isinstance(frame, CursorImage) else frame).copy()

    def set_border(self, color) -> None:
        self.border = color


class Listener:
    def __init__(self, **_kwargs) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class Audio:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.events = deque()

    def start(self) -> bool:
        self.started = True
        return True

    def poll(self) -> list[AudioHintEvent]:
        events = list(self.events)
        self.events.clear()
        return events

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class InputAction:
    time: float
    kind: str
    args: tuple
    thread_id: int


class Replay:
    def __init__(self, monkeypatch, directory: Path, *, config: RuntimeConfig | None = None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.root = VirtualRoot()
        self.window = WindowInfo("Minecraft", 18, 30, 1280, 748, owner="java")
        self.actions: list[InputAction] = []
        self.results = []
        self.steps = []
        self.capture_boxes = []
        self.inputs = []
        self.capture_started = threading.Event()
        self.capture_release = threading.Event()
        self.capture_release.set()
        self.backends = []
        self.workers = []
        self.audio = Audio()
        self.frame = self.fishing_frame()
        self.capture_error = None
        self.log_path = directory / "session" / "replay.log"
        self.log_path.parent.mkdir()
        self.log_path.touch()
        monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(self.log_path))
        monkeypatch.setenv("AUTOANGLER_MAX_CAPTURE_FPS", "10")
        monkeypatch.setenv("AUTOANGLER_RECORD_INTERVAL_MS", "50")
        monkeypatch.delenv("AUTOANGLER_LINE_DARKNESS_THRESHOLD", raising=False)

        def forbidden(*_args, **_kwargs):
            raise AssertionError("Unexpected native desktop access during replay")

        replay = self

        class Capture:
            backend_name = "replay"

            def __init__(self):
                self.closed = False
                replay.backends.append(self)

            def grab(self, bbox=None):
                replay.capture_boxes.append(bbox)
                if replay.capture_error:
                    raise OSError(replay.capture_error)
                assert bbox is not None
                assert replay.window is not None
                window = replay.window
                assert bbox == (
                    window.left,
                    window.top,
                    window.left + window.width,
                    window.top + window.height,
                )
                frame = replay.frame.copy()
                replay.inputs.append(frame)
                replay.capture_started.set()
                if not replay.capture_release.wait(timeout=5):
                    raise TimeoutError("Replay capture was not released")
                return frame

            def close(self):
                self.closed = True

        class ObservedWorker(async_pipeline.VisionWorker):
            def __init__(self):
                super().__init__()
                # Queue has the same poll interface, plus bounded get for the driver.
                self._results = Queue()
                replay.workers.append(self)

        for module in (capture_backend, cursor_camera, cursor_locator, gui_tk, async_pipeline):
            monkeypatch.setattr(module, "create_capture_backend", Capture)
        monkeypatch.setattr(capture_backend.MSSCaptureBackend, "grab", forbidden)
        monkeypatch.setattr(capture_backend.PillowCaptureBackend, "grab", forbidden)
        monkeypatch.setattr(capture_backend.ImageGrab, "grab", forbidden)
        for name in (
            "click",
            "leftClick",
            "middleClick",
            "doubleClick",
            "press",
            "write",
            "typewrite",
            "hotkey",
            "moveTo",
            "mouseDown",
            "mouseUp",
            "dragTo",
            "dragRel",
            "scroll",
            "hscroll",
            "vscroll",
            "screenshot",
            "position",
            "size",
            "getActiveWindow",
            "getAllWindows",
        ):
            monkeypatch.setattr(gui_tk.pyautogui, name, forbidden, raising=False)
        for module in (cursor_camera, cursor_locator, gui_tk):
            monkeypatch.setattr(
                module, "get_virtual_screen_bounds", lambda: ScreenBounds(-2000, -2000, 6000, 6000)
            )
        monkeypatch.setattr(gui_tk, "selected_minecraft_window", lambda: self.window)
        monkeypatch.setattr(gui_tk.keyboard, "Listener", Listener)
        monkeypatch.setattr(gui_tk, "AudioHintMonitor", forbidden)
        monkeypatch.setattr(gui_tk, "VisionWorker", ObservedWorker)
        for name in ("rightClick", "keyDown", "keyUp", "moveRel"):

            def record(*args, _kind=name, **_kwargs):
                self.actions.append(
                    InputAction(round(self.root.now, 6), _kind, args, threading.get_ident())
                )

            monkeypatch.setattr(gui_tk.pyautogui, name, record)
        monkeypatch.setattr(gui_tk, "monotonic", lambda: self.root.now)
        monkeypatch.setattr(gui_tk, "time", lambda: self.root.now)
        monkeypatch.setattr(gui_tk, "sleep", lambda seconds: self.advance(round(seconds * 1000)))
        monkeypatch.setattr(async_pipeline, "monotonic", lambda: self.root.now)
        self.app = gui_tk.AutoFishTkApp(
            runtime_config=config or RuntimeConfig(auto_strafe_enabled=False),
            audio_monitor=self.audio,
        )
        self.app._random = random.Random(17)
        self.app._root = self.root
        self.app._status_var = Value()
        self.app._line_state_var = Value()
        self.app._catch_var = Value()
        self.app._viewer = Preview()
        self.app._debug_viewer = Preview()
        self.app._ensure_audio_monitor()

    def fishing_frame(self, *, strength: str = "stable", rod: bool = True) -> np.ndarray:
        window = self.window
        assert window is not None
        frame = np.full((window.height, window.width, 3), 180, dtype=np.uint8)
        # Independent scene geometry: the line is below the central crosshair.
        x, y = window.width // 2, window.height // 2 + 24
        length = {"stable": 30, "weak": 6, "gone": 0}[strength]
        frame[y : y + length, x : x + 2] = 0
        if rod:
            template = cv2.imread(str(files("autoangler.assets") / "fishing_rod_slot_template.png"))
            assert template is not None
            height, width = template.shape[:2]
            top = window.height - max(48, int(window.height * 0.14))
            left = (window.width - width) // 2
            frame[top : top + height, left : left + width] = template
        return frame

    def scene(self, strength: str = "stable", *, rod: bool = True) -> None:
        self.frame = self.fishing_frame(strength=strength, rod=rod)
        self.steps.append({"time": self.root.now, "scene": strength, "rod": rod})

    def pause_scene(self) -> None:
        path = Path(__file__).parent / "fixtures" / "pause_menu" / "pause-menu-open.png"
        self.frame = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
        self.steps.append({"time": self.root.now, "scene": "pause_menu"})

    def advance(self, milliseconds: int) -> None:
        self.root.advance(milliseconds)

    def key(self, name: str) -> None:
        self.steps.append({"time": self.root.now, "key": name})
        self.app._on_key_press(getattr(gui_tk.keyboard.Key, name))
        self.advance(0)

    def start(self, *, menu: bool = False) -> None:
        if menu:
            self.app._toggle_fishing()
        else:
            self.key("f12")

    def stop(self) -> None:
        self.key("f12")

    def _tick(self) -> None:
        self.app._tick()
        # The driver explicitly controls frame cadence, not Tk's wall-clock timer.
        self.root.remove_callback(self.app._tick)

    def observe(self):
        self.advance(110)
        self._tick()
        worker = self.app._vision_worker
        assert worker is not None
        result = worker._results.get(timeout=5)
        self.results.append(result)
        worker._results.put(result)
        self._tick()
        self.steps.append({"time": self.root.now, "state": self.state})
        return result

    def deliver(self, result) -> None:
        self.app._ensure_vision_worker()._results.put(result)
        self.app._drain_vision_results()
        self.app._refresh_ui_state()

    @property
    def state(self) -> dict:
        return {
            "fishing": self.app._is_fishing,
            "line_out": self.app._is_line_out,
            "casts": self.app._cast_count,
            "catches": self.app._catch_count,
            "preview": self.app._preview_state,
            "status": self.app._status_var.get(),
            "counter": self.app._catch_var.get(),
        }

    @property
    def clicks(self) -> list[InputAction]:
        return [action for action in self.actions if action.kind == "rightClick"]

    def trace(self) -> list[dict]:
        path = self.log_path.with_name("replay-trace.csv")
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle))

    def close(self) -> None:
        self.capture_release.set()
        recording_worker = self.app._recording_worker
        self.app._quit()
        self.app._quit()
        if recording_worker is not None:
            assert not recording_worker._thread.is_alive()
        for worker in self.workers:
            assert not worker._thread.is_alive()
        assert self.app._keyboard_listener.stopped
        assert self.audio.closed
        assert self.backends[0].closed

    def save_evidence(self) -> None:
        (self.directory / "timeline.json").write_text(
            json.dumps(
                {
                    "actions": [asdict(action) for action in self.actions],
                    "steps": self.steps,
                    "final_state": self.state,
                    "capture_boxes": self.capture_boxes,
                },
                indent=2,
            )
            + "\n"
        )
        cv2.imwrite(
            str(self.directory / "last-input.png"), cv2.cvtColor(self.frame, cv2.COLOR_RGB2BGR)
        )
        for index, result in enumerate(self.results):
            cv2.imwrite(
                str(self.directory / f"result-{index:03}-mask.png"),
                result.tracking_preview.computer,
            )
        for index, frame in enumerate(self.inputs):
            cv2.imwrite(
                str(self.directory / f"input-{index:03}.png"),
                cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
            )
