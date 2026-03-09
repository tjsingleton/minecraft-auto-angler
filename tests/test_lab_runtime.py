from __future__ import annotations

from pathlib import Path

from autoangler.audio_probe import AudioHintEvent
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
    )

    header, row = path.read_text().splitlines()
    assert "cast_settle_min_ms" in header
    assert "scheduled_delay_ms" in header
    assert "audio_hint_rms" in header
    assert "audio_hint_peak" in header
    assert "auto_strafe_enabled" in header
    assert "strafe_direction" in header
    assert "strafe_duration_ms" in header
    assert ",420,0.3100,0.4400,left,150,vision" in row


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
    assert ",2800,3200,350,900,1,1,0," in row
    assert row.endswith(",100.0,70.0,10.0,15.0,5.0,0,0")


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
    assert ",0.2100,0.4400,,,audio,," in content


def test_reel_and_recast_logs_auto_strafe_before_cast(monkeypatch) -> None:
    app = AutoFishTkApp(
        runtime_config=RuntimeConfig(
            recast=DelayRange(minimum_ms=300, maximum_ms=1000),
            auto_strafe_enabled=True,
        )
    )
    scheduled: list[tuple[int, object]] = []
    choices = iter([640, 180])
    trace_calls: list[dict[str, object]] = []
    input_calls: list[tuple[str, str | float]] = []

    class FakeRoot:
        def after(self, delay_ms: int, callback) -> None:
            scheduled.append((delay_ms, callback))

    app._root = FakeRoot()
    monkeypatch.setattr(app, "_reel", lambda source="system": None)
    monkeypatch.setattr(app, "_cast", lambda: None)
    monkeypatch.setattr(
        app,
        "_choose_delay_ms",
        lambda _range: next(choices),
    )
    monkeypatch.setattr(
        app,
        "_choose_strafe_direction",
        lambda: "left",
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
        "autoangler.gui_tk.sleep",
        lambda seconds: input_calls.append(("sleep", seconds)),
    )
    app._recording_enabled = True

    app._reel_and_recast(source="vision")

    assert input_calls == [("down", "a"), ("sleep", 0.18), ("up", "a")]
    assert any(call["event"] == "strafe" for call in trace_calls)
    assert scheduled == [(460, app._cast)]


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
                "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,bite_detected,cast_settle_min_ms,cast_settle_max_ms,recast_min_ms,recast_max_ms,audio_hints_enabled,auto_strafe_enabled,scheduled_delay_ms,audio_hint_rms,audio_hint_peak,strafe_direction,strafe_duration_ms,source,training_label,rod_in_hand,catch_count",
                (
                    "1.0,cast,1,0,0,0,0,0,2800,3200,300,1000,1,1,,,,,,"
                    "system,,0,0"
                ).replace(" ,", ","),
                "2.0,audio_hint,1,1,42,10,1,0,2800,3200,300,1000,1,1,,0.2100,0.4400,,,audio,,0,0",
                "3.0,strafe,1,1,10,5,2,1,2800,3200,300,1000,1,1,,,,left,180,auto_strafe,,1,1",
                "4.0,recast_scheduled,1,1,10,5,2,1,2800,3200,300,1000,1,1,420,,,,,vision,,1,1",
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
    assert summary["triggerSequence"][3]["scheduledDelayMs"] == 420
