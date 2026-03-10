from __future__ import annotations

from autoangler.gui_tk import AutoFishTkApp
from autoangler.minecraft_window import WindowInfo


def test_submit_vision_request_uses_idle_preview_mode_and_two_fps() -> None:
    app = AutoFishTkApp()
    app._minecraft_window = WindowInfo(title="Minecraft", left=0, top=0, width=1000, height=700)
    app._fishing_roi = (100, 100, 400, 300)
    submitted: list[tuple[int, str]] = []

    class FakeWorker:
        dropped_frames = 0

        def submit(self, request) -> None:
            submitted.append((request.seq, request.mode))

    app._vision_worker = FakeWorker()  # type: ignore[assignment]
    app._vision_epoch = 1

    app._submit_vision_request(now=1.0)
    app._submit_vision_request(now=1.2)
    app._submit_vision_request(now=1.6)

    assert submitted == [(1, "idle_preview"), (2, "idle_preview")]


def test_tick_does_not_append_profile_row_for_idle_preview() -> None:
    app = AutoFishTkApp()
    profile_calls: list[str] = []

    class FakeRoot:
        def after(self, _delay_ms: int, _callback) -> None:
            return None

    app._root = FakeRoot()
    app._minecraft_window = WindowInfo(title="Minecraft", left=0, top=0, width=1000, height=700)
    app._fishing_roi = (100, 100, 400, 300)
    app._drain_recording_events = lambda: None  # type: ignore[method-assign]
    app._drain_vision_results = lambda: None  # type: ignore[method-assign]
    app._maybe_refresh_tracking_context = lambda *, now: None  # type: ignore[method-assign]
    app._submit_vision_request = lambda *, now: None  # type: ignore[method-assign]
    app._maybe_record_frame = lambda *, now: None  # type: ignore[method-assign]
    app._drain_audio_hints = lambda *, now: None  # type: ignore[method-assign]
    app._append_profile_row = lambda **_kwargs: profile_calls.append("profile")  # type: ignore[method-assign]

    app._tick()

    assert profile_calls == []


def test_bootstrap_idle_preview_locates_and_seeds_without_calibration(monkeypatch) -> None:
    app = AutoFishTkApp()
    calls: list[str] = []

    monkeypatch.setattr(app, "_locate_minecraft_window", lambda: calls.append("locate") or True)
    monkeypatch.setattr(app, "_seed_default_guide_boxes", lambda: calls.append("seed"))
    monkeypatch.setattr(app, "_calibrate_line", lambda: calls.append("calibrate"))

    app._bootstrap_idle_preview()

    assert calls == ["locate", "seed"]


def test_preview_border_color_is_neutral_during_idle_preview() -> None:
    app = AutoFishTkApp()
    app._preview_state = "neutral"

    assert app._preview_border_color() == "#68727c"
