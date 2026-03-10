from __future__ import annotations

from pathlib import Path

import numpy as np

from autoangler.async_pipeline import VisionResult
from autoangler.audio_probe import AudioHintEvent
from autoangler.cursor_image import CursorImage
from autoangler.gui_tk import AutoFishTkApp
from autoangler.profile_session import summarize_session
from autoangler.runtime_config import DelayRange, RuntimeConfig


def test_cast_schedules_line_out_using_selected_runtime_delay(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
        )
    )
    scheduled: list[tuple[int, object]] = []
    chosen: list[tuple[int, int]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            scheduled.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(
        app,
        "_choose_delay_ms",
        lambda delay_range: chosen.append((delay_range.minimum_ms, delay_range.maximum_ms)) or 3105,
    )
    monkeypatch.setattr(app, "_use_rod", lambda: None)

    app._cast()

    assert chosen == [(2800, 3200)]
    assert scheduled == [(3105, app._mark_line_out)]


def test_reel_and_recast_uses_selected_runtime_delay(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            recast=DelayRange(minimum_ms=350, maximum_ms=900),
            auto_strafe_enabled=False,
        )
    )
    actions: list[str] = []
    scheduled: list[tuple[int, object]] = []
    chosen: list[tuple[int, int]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            scheduled.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(
        app,
        "_choose_delay_ms",
        lambda delay_range: chosen.append((delay_range.minimum_ms, delay_range.maximum_ms)) or 420,
    )
    monkeypatch.setattr(app, "_reel", lambda source="system": actions.append(source))
    monkeypatch.setattr(app, "_cast", lambda: actions.append("cast"))
    monkeypatch.setattr(app, "_maybe_auto_strafe", lambda **kwargs: kwargs["total_delay_ms"])

    app._reel_and_recast(source="vision")

    assert chosen == [(350, 900)]
    assert actions == ["vision"]
    assert scheduled == [(420, app._cast)]


def test_append_trace_row_writes_runtime_metadata_and_timing_fields(
    tmp_path: Path, monkeypatch
) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
            recast=DelayRange(minimum_ms=350, maximum_ms=900),
            audio_hints_enabled=True,
            auto_strafe_enabled=True,
        )
    )
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))

    path = app._append_trace_row(
        now=1.0,
        event="recast_scheduled",
        source="vision",
        scheduled_delay_ms=420,
        audio_hint_rms=0.31,
        audio_hint_peak=0.44,
        strafe_direction="left",
        strafe_duration_ms=150,
        strafe_offset_steps=2,
        mouse_dx_px=4,
        mouse_dy_px=-2,
        mouse_offset_x_px=8,
        mouse_offset_y_px=-4,
    )

    header, row = path.read_text().splitlines()
    assert "cast_settle_min_ms" in header
    assert "scheduled_delay_ms" in header
    assert "audio_hint_rms" in header
    assert "audio_hint_peak" in header
    assert "auto_strafe_enabled" in header
    assert "strafe_direction" in header
    assert "strafe_duration_ms" in header
    assert "strafe_offset_steps" in header
    assert "mouse_dx_px" in header
    assert "mouse_dy_px" in header
    assert "mouse_offset_x_px" in header
    assert "mouse_offset_y_px" in header
    assert ",420,0.3100,0.4400,left,150,2,4,-2,8,-4,vision" in row


def test_append_profile_row_writes_runtime_metadata(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
            recast=DelayRange(minimum_ms=350, maximum_ms=900),
            audio_hints_enabled=True,
            auto_strafe_enabled=True,
        )
    )
    log_path = tmp_path / "sessions" / "s" / "s.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))

    path = app._append_profile_row(
        now=1.0,
        total_ms=100.0,
        capture_ms=70.0,
        detect_ms=10.0,
        preview_ms=15.0,
        record_ms=5.0,
    )

    header, row = path.read_text().splitlines()
    assert "cast_settle_min_ms" in header
    assert "auto_strafe_enabled" in header
    assert "vision_age_ms" in header
    assert ",2800,3200,350,900,1,1,0," in row
    assert row.endswith(",100.0,70.0,10.0,15.0,5.0,0.0,0,0,0,0,0")


def test_drain_audio_hints_records_trace_event(tmp_path: Path, monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(audio_hints_enabled=True),
    )
    log_path = tmp_path / "sessions" / "20260307-213938.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AUTOANGLER_SESSION_LOG", str(log_path))
    app._recording_enabled = True
    app._audio_monitor = type(
        "FakeAudioMonitor",
        (),
        {
            "poll": lambda self: [
                AudioHintEvent(timestamp=2.5, rms=0.21, peak=0.44),
            ]
        },
    )()

    app._drain_audio_hints(now=5.0)

    content = (tmp_path / "sessions" / "20260307-213938-trace.csv").read_text()
    assert ",audio_hint,0,0,0,0,0,0,3000,3000,300,1000,1,1,," in content
    assert ",0.2100,0.4400,,,,,,,,audio,," in content


def test_reel_and_recast_logs_auto_strafe_before_cast(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            recast=DelayRange(minimum_ms=300, maximum_ms=1000),
            auto_strafe_enabled=True,
        )
    )
    scheduled: list[tuple[int, object]] = []
    choices = iter([640, 420])
    trace_calls: list[dict[str, object]] = []
    input_calls: list[tuple[str, str | float]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            scheduled.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda source="system": None)
    monkeypatch.setattr(app, "_cast", lambda: None)
    monkeypatch.setattr(app, "_movement_state", app._movement_state.__class__())
    monkeypatch.setattr(
        app,
        "_choose_delay_ms",
        lambda _range: next(choices),
    )
    monkeypatch.setattr(app, "_choose_next_strafe_offset", lambda current: current + 1)
    monkeypatch.setattr(
        app,
        "_choose_next_mouse_offset",
        lambda current, *, step_px, max_px: current,
    )
    monkeypatch.setattr(
        app,
        "_append_trace_row",
        lambda **kwargs: trace_calls.append(kwargs) or Path("/tmp/trace.csv"),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyDown",
        lambda key: input_calls.append(("down", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyUp",
        lambda key: input_calls.append(("up", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.moveRel",
        lambda dx, dy, duration=0: input_calls.append(("move", (dx, dy, duration))),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.sleep",
        lambda seconds: input_calls.append(("sleep", seconds)),
    )
    app._recording_enabled = True

    app._reel_and_recast(source="vision")

    assert input_calls == [("down", "d"), ("sleep", 0.3), ("up", "d")]
    assert any(
        call["event"] == "strafe"
        and call["strafe_offset_steps"] == 1
        and call["mouse_dx_px"] == 0
        and call["mouse_offset_x_px"] == 0
        for call in trace_calls
    )
    assert scheduled == [(340, app._cast)]


def test_maybe_auto_strafe_skips_when_disabled(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(auto_strafe_enabled=False),
    )
    calls: list[str] = []
    monkeypatch.setattr("autoangler.gui_tk.pyautogui.keyDown", lambda _key: calls.append("down"))
    monkeypatch.setattr("autoangler.gui_tk.pyautogui.keyUp", lambda _key: calls.append("up"))

    remaining = app._maybe_auto_strafe(total_delay_ms=500)

    assert remaining == 500
    assert calls == []


def test_movement_wander_can_build_distance_across_casts(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(auto_strafe_enabled=True),
    )
    calls: list[tuple[str, str | float]] = []
    offsets = iter([1, 2, 3])

    monkeypatch.setattr(app, "_choose_next_strafe_offset", lambda current: next(offsets))
    monkeypatch.setattr(
        app,
        "_choose_next_mouse_offset",
        lambda current, *, step_px, max_px: current,
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyDown",
        lambda key: calls.append(("down", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyUp",
        lambda key: calls.append(("up", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.sleep",
        lambda seconds: calls.append(("sleep", seconds)),
    )

    remaining_1 = app._maybe_auto_strafe(total_delay_ms=900)
    remaining_2 = app._maybe_auto_strafe(total_delay_ms=900)
    remaining_3 = app._maybe_auto_strafe(total_delay_ms=900)

    assert calls == [
        ("down", "d"),
        ("sleep", 0.3),
        ("up", "d"),
        ("down", "d"),
        ("sleep", 0.3),
        ("up", "d"),
        ("down", "d"),
        ("sleep", 0.3),
        ("up", "d"),
    ]
    assert app._movement_state.current_strafe_offset_steps == 3
    assert remaining_1 == 600
    assert remaining_2 == 600
    assert remaining_3 == 600


def test_movement_wander_biases_back_toward_zero(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._movement_state.current_strafe_offset_steps = 4

    target = app._choose_next_strafe_offset(4)

    assert target == 3


def test_movement_state_reset_clears_strafe_and_mouse_offsets() -> None:
    app = AutoFishTkApp()
    app._movement_state.current_strafe_offset_steps = 3
    app._movement_state.current_mouse_offset_x_px = 12
    app._movement_state.current_mouse_offset_y_px = -6

    app._reset_movement_state()

    assert app._movement_state.current_strafe_offset_steps == 0
    assert app._movement_state.current_mouse_offset_x_px == 0
    assert app._movement_state.current_mouse_offset_y_px == 0


def test_stop_resets_movement_state() -> None:
    app = AutoFishTkApp()
    app._movement_state.current_strafe_offset_steps = 3
    app._movement_state.current_mouse_offset_x_px = 12
    app._movement_state.current_mouse_offset_y_px = -6

    class FakeButton:
        def configure(self, **_kwargs) -> None:
            return None

    app._button = FakeButton()

    app._stop()

    assert app._movement_state.current_strafe_offset_steps == 0
    assert app._movement_state.current_mouse_offset_x_px == 0
    assert app._movement_state.current_mouse_offset_y_px == 0


def test_maybe_auto_strafe_applies_small_mouse_drift(monkeypatch) -> None:
    app = AutoFishTkApp(runtime_config=RuntimeConfig(auto_strafe_enabled=True))
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(app, "_choose_next_strafe_offset", lambda current: current)
    monkeypatch.setattr(
        app,
        "_choose_next_mouse_offset",
        lambda current, *, step_px, max_px: current + step_px,
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.moveRel",
        lambda dx, dy, duration=0: calls.append(("move", (dx, dy, duration))),
    )

    remaining = app._maybe_auto_strafe(total_delay_ms=400)

    assert calls == [("move", (4, 2, 0))]
    assert app._movement_state.current_mouse_offset_x_px == 4
    assert app._movement_state.current_mouse_offset_y_px == 2
    assert remaining == 400


def test_maybe_auto_strafe_reduces_mouse_drift_when_delay_budget_is_tight(monkeypatch) -> None:
    app = AutoFishTkApp(runtime_config=RuntimeConfig(auto_strafe_enabled=True))
    app._movement_state.current_strafe_offset_steps = 0
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(app, "_choose_next_strafe_offset", lambda current: current + 1)
    monkeypatch.setattr(
        app,
        "_choose_next_mouse_offset",
        lambda current, *, step_px, max_px: current + step_px,
    )
    monkeypatch.setattr(
        app,
        "_choose_delay_ms",
        lambda _delay_range: 420,
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyDown",
        lambda key: calls.append(("down", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.keyUp",
        lambda key: calls.append(("up", key)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.sleep",
        lambda seconds: calls.append(("sleep", seconds)),
    )
    monkeypatch.setattr(
        "autoangler.gui_tk.pyautogui.moveRel",
        lambda dx, dy, duration=0: calls.append(("move", (dx, dy, duration))),
    )

    remaining = app._maybe_auto_strafe(total_delay_ms=320)

    assert calls == [("down", "d"), ("sleep", 0.3), ("up", "d"), ("move", (1, 0, 0))]
    assert app._movement_state.current_strafe_offset_steps == 1
    assert app._movement_state.current_mouse_offset_x_px == 1
    assert app._movement_state.current_mouse_offset_y_px == 0
    assert remaining == 20


def test_summarize_session_reports_event_counts_and_trigger_sequence(tmp_path: Path) -> None:
    profile_csv = tmp_path / "20260309-120000-profile.csv"
    trace_csv = tmp_path / "20260309-120000-trace.csv"
    profile_csv.write_text(
        "\n".join(
            [
                "time_s,cast_settle_min_ms,cast_settle_max_ms,recast_min_ms,recast_max_ms,audio_hints_enabled,auto_strafe_enabled,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,record_ms,line_pixels,trigger_pixels",
                "1.0,2800,3200,300,1000,1,1,1,1,100.0,70.0,10.0,15.0,5.0,10,5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    trace_csv.write_text(
        "\n".join(
            [
                "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,bite_detected,cast_settle_min_ms,cast_settle_max_ms,recast_min_ms,recast_max_ms,audio_hints_enabled,auto_strafe_enabled,scheduled_delay_ms,audio_hint_rms,audio_hint_peak,strafe_direction,strafe_duration_ms,strafe_offset_steps,mouse_dx_px,mouse_dy_px,mouse_offset_x_px,mouse_offset_y_px,source,training_label,rod_in_hand,catch_count",
                ",".join(
                    [
                        "1.0",
                        "cast",
                        "1",
                        "0",
                        "0",
                        "0",
                        "0",
                        "0",
                        "2800",
                        "3200",
                        "300",
                        "1000",
                        "1",
                        "1",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "system",
                        "",
                        "0",
                        "0",
                    ]
                ),
                ",".join(
                    [
                        "2.0",
                        "audio_hint",
                        "1",
                        "1",
                        "42",
                        "10",
                        "1",
                        "0",
                        "2800",
                        "3200",
                        "300",
                        "1000",
                        "1",
                        "1",
                        "",
                        "0.2100",
                        "0.4400",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "audio",
                        "",
                        "0",
                        "0",
                    ]
                ),
                ",".join(
                    [
                        "3.0",
                        "strafe",
                        "1",
                        "1",
                        "10",
                        "5",
                        "2",
                        "1",
                        "2800",
                        "3200",
                        "300",
                        "1000",
                        "1",
                        "1",
                        "",
                        "",
                        "",
                        "left",
                        "180",
                        "2",
                        "4",
                        "-2",
                        "8",
                        "-4",
                        "auto_strafe",
                        "",
                        "1",
                        "1",
                    ]
                ),
                ",".join(
                    [
                        "4.0",
                        "recast_scheduled",
                        "1",
                        "1",
                        "10",
                        "5",
                        "2",
                        "1",
                        "2800",
                        "3200",
                        "300",
                        "1000",
                        "1",
                        "1",
                        "420",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "vision",
                        "",
                        "1",
                        "1",
                    ]
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_session(profile_csv)

    assert summary["audioHintsEnabled"] is True
    assert summary["autoStrafeEnabled"] is True
    assert summary["eventCounts"] == {
        "cast": 1,
        "audio_hint": 1,
        "strafe": 1,
        "recast_scheduled": 1,
    }
    assert summary["triggerSequence"][1]["source"] == "audio"
    assert summary["triggerSequence"][2]["strafeDirection"] == "left"
    assert summary["triggerSequence"][2]["strafeOffsetSteps"] == 2
    assert summary["triggerSequence"][2]["mouseDxPx"] == 4
    assert summary["triggerSequence"][2]["mouseOffsetXPx"] == 8
    assert summary["triggerSequence"][3]["scheduledDelayMs"] == 420


def test_apply_vision_result_ignores_stale_epoch(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._vision_epoch = 4
    app._last_applied_vision_seq = 10
    app._line_pixels = 12
    app._rod_in_hand = True
    calls: list[str] = []

    monkeypatch.setattr(app, "_reel_and_recast", lambda source="system": calls.append(source))

    applied = app._apply_vision_result(_vision_result(epoch=3, seq=11, line_pixels=0))

    assert applied is False
    assert app._line_pixels == 12
    assert app._rod_in_hand is True
    assert calls == []


def test_apply_vision_result_updates_state_on_main_thread(monkeypatch) -> None:
    app = AutoFishTkApp()
    app._vision_epoch = 2
    app._last_applied_vision_seq = 0
    app._is_fishing = True
    app._is_line_out = True
    app._viewer = type("Viewer", (), {"update": lambda self, image: None})()
    app._debug_viewer = type("Viewer", (), {"update": lambda self, image, secondary=None: None})()
    app._line_watcher.observe(20, active=True)
    events: list[str] = []

    monkeypatch.setattr(
        app,
        "_record_detection_event",
        lambda **_kwargs: events.append("detection"),
    )
    monkeypatch.setattr(app, "_reel_and_recast", lambda source="system": events.append(source))

    applied = app._apply_vision_result(_vision_result(epoch=2, seq=1, line_pixels=0))

    assert applied is True
    assert app._last_applied_vision_seq == 1
    assert app._line_pixels == 0
    assert app._bite_detected is True
    assert events == ["detection", "vision"]


def _vision_result(*, epoch: int, seq: int, line_pixels: int) -> VisionResult:
    original = np.full((6, 6), 255, dtype=np.uint8)
    computer = np.full((6, 6), 255, dtype=np.uint8)
    return VisionResult(
        epoch=epoch,
        seq=seq,
        completed_at=1.25,
        window_frame=original,
        main_preview_frame=original,
        tracking_preview=CursorImage(
            original=original,
            computer=computer,
            black_pixel_count=line_pixels,
        ),
        debug_composite=np.zeros((6, 12, 3), dtype=np.uint8),
        preview_state="invalid",
        rod_in_hand=False,
        line_candidate=None,
        line_pixels=line_pixels,
        suggested_tracking_box=(1, 1, 4, 4),
        suggested_detection_box=(2, 2, 5, 5),
        capture_ms=10.0,
        detect_ms=4.0,
        annotate_ms=3.0,
        capture_error=None,
    )
