"""Bounded real-Tk scenario. Native capture, audio, listening, and input remain fake."""

from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path

from pytest import MonkeyPatch

from autoangler import async_pipeline, gui_tk
from autoangler.image_viewer_tk import ImageViewerTk
from autoangler.runtime_config import DelayRange, RuntimeConfig
from tests.replay_support import Replay


def main(directory: Path) -> None:
    errors = []
    preview_threads = []
    main_thread = threading.get_ident()
    config = RuntimeConfig(cast_settle=DelayRange(0, 0), auto_strafe_enabled=False)
    with MonkeyPatch.context() as patch:
        replay = Replay(patch, directory, config=config)
        app = replay.app
        patch.setattr(gui_tk, "monotonic", time.monotonic)
        patch.setattr(gui_tk, "time", time.time)
        patch.setattr(async_pipeline, "monotonic", time.monotonic)

        def enable_listener():
            app._keyboard_listener.start()
            return True

        patch.setattr(app, "_try_enable_hotkeys", enable_listener)
        original_update = ImageViewerTk.update

        def update(viewer, *args, **kwargs):
            preview_threads.append(threading.get_ident())
            return original_update(viewer, *args, **kwargs)

        patch.setattr(ImageViewerTk, "update", update)
        original_tk = tk.Tk
        thread = None
        phase = 0

        def fail(exc_type, value, tb):
            errors.append("".join(traceback.format_exception(exc_type, value, tb)))
            app._quit()

        def poll():
            nonlocal phase
            root = app._root
            if phase == 0:
                if (
                    thread.is_alive()
                    or not app._is_line_out
                    or app._catch_var.get() != "0 / 1"
                    or not app._rod_in_hand
                ):
                    root.after(20, poll)
                    return
                assert app._keyboard_listener.started
                assert app._catch_var.get() == "0 / 1"
                assert app._fishing_dot.itemcget(1, "fill") == "#1f8f3a"
                assert app._viewer._elements.primary_label.cget("image")
                replay.key("esc")
                assert app._is_fishing
                replay.key("f7")
                replay.key("f9")
                replay.key("f10")
                phase = 1
            elif phase == 1:
                assert app._recording_enabled
                assert not app._debug_window.winfo_viewable()
                assert app._line_candidate is not None
                replay.key("f8")
                replay.key("f12")
                replay.key("f7")
                phase = 2
            else:
                assert not app._is_fishing and not app._recording_enabled
                assert app._catch_count == 0
                assert len(replay.clicks) == 2
                assert {action.thread_id for action in replay.actions} == {main_thread}
                assert set(preview_threads) == {main_thread}
                root.tk.call(root.protocol("WM_DELETE_WINDOW"))
                return
            root.after(50, poll)

        def begin():
            nonlocal thread
            root = app._root
            root.geometry("384x328+421+137")
            menu = root.nametowidget(root.cget("menu"))
            view = root.nametowidget(menu.entrycget("View", "menu"))
            view.invoke("Always On Top")
            assert not app._topmost_enabled
            view.invoke("Debug Window")
            root.update_idletasks()
            assert app._debug_window.winfo_viewable()
            thread = threading.Thread(target=app._on_key_press, args=(gui_tk.keyboard.Key.f12,))
            thread.start()
            # The listener thread schedules work; input cannot run inside this Tk callback.
            assert replay.clicks == []
            root.after(20, poll)

        def timeout():
            raise TimeoutError("Tk scenario did not complete in eight seconds")

        def create_root(*args, **kwargs):
            root = original_tk(*args, **kwargs)
            root.report_callback_exception = fail
            root.after(50, begin)
            root.after(8000, timeout)
            return root

        patch.setattr(tk, "Tk", create_root)
        try:
            app.run()
        finally:
            replay.close()
            replay.save_evidence()
        assert not errors, "\n".join(errors)
        assert phase == 2
        assert thread is not None
        thread.join(timeout=1)
        assert not thread.is_alive()
        state = json.loads(app._window_state_path().read_text())
        assert state["position"] == "+421+137"
        assert state["topmost"] is False
        (directory / "tk-result.json").write_text(
            json.dumps(
                {
                    "phase": phase,
                    "preview_updates": len(preview_threads),
                    "clicks": len(replay.clicks),
                    "geometry": state,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
