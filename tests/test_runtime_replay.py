from __future__ import annotations

import json
import threading
from dataclasses import replace

import cv2
import numpy as np
import pytest

from autoangler.audio_probe import AudioHintEvent
from autoangler.profile_session import summarize_session
from autoangler.runtime_config import DelayRange, RuntimeConfig


@pytest.mark.parametrize("menu", [False, True], ids=["f12", "menu"])
def test_complete_fishing_cycle(replay, menu):
    replay.start(menu=menu)
    if menu:
        assert replay.clicks == []
        replay.advance(4999)
        assert replay.clicks == []
        replay.advance(1)
    assert len(replay.clicks) == 1
    cast_at = replay.clicks[0].time
    replay.advance(2999)
    assert replay.state["line_out"] is False
    replay.advance(1)
    assert replay.state["line_out"] is True

    stable = replay.observe()
    assert stable.rod_in_hand is True
    assert stable.line_candidate is not None
    assert stable.line_pixels == 60
    assert replay.state["preview"] == "valid"
    assert replay.state["counter"] == "0 / 1"
    assert len(replay.clicks) == 1

    replay.scene("gone")
    replay.observe()
    assert replay.state["catches"] == 1
    assert len(replay.clicks) == 2
    reel_at = replay.clicks[-1].time
    replay.advance(299)
    assert len(replay.clicks) == 2
    replay.advance(701)
    assert len(replay.clicks) == 3
    assert 0.3 <= round(replay.clicks[-1].time - reel_at, 6) <= 1.0
    assert replay.clicks[-1].time >= cast_at + 3
    assert replay.state["casts"] == 2
    assert replay.state["catches"] == 1
    assert set(replay.app._viewer.thread_ids) == {threading.get_ident()}


def test_weak_frames_require_two_observations_and_recovery_resets_streak(replay):
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.scene("weak")
    assert replay.observe().line_pixels == 12
    assert len(replay.clicks) == 1
    replay.scene()
    replay.observe()
    replay.scene("weak")
    replay.observe()
    assert len(replay.clicks) == 1
    replay.observe()
    assert len(replay.clicks) == 2
    assert replay.state["catches"] == 1


@pytest.mark.parametrize("phase", ["countdown", "settling", "recast"])
def test_stop_invalidates_pending_actions_and_restart_results(replay, phase):
    replay.start(menu=phase == "countdown")
    if phase == "recast":
        replay.advance(3000)
        replay.observe()
        replay.scene("gone")
    old_result = replay.observe()
    replay.stop()
    stopped_clicks = list(replay.clicks)
    replay.advance(10000)
    replay.deliver(old_result)
    assert replay.clicks == stopped_clicks
    assert replay.state["fishing"] is False
    assert replay.state["line_out"] is False

    replay.scene()
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.deliver(replace(old_result, line_pixels=0, seq=10000))
    assert len(replay.clicks) == len(stopped_clicks) + 1
    assert replay.state["catches"] == 0


def test_duplicate_older_and_stale_results_have_no_effect(replay):
    replay.start()
    replay.advance(3000)
    result = replay.observe()
    before = replay.state.copy()
    preview = replay.app._viewer.frame.copy()
    for rejected in (
        replace(result, line_pixels=0),
        replace(result, seq=result.seq - 1, line_pixels=0),
        replace(result, seq=result.seq + 100, epoch=result.epoch - 1, line_pixels=0),
    ):
        replay.deliver(rejected)
        assert replay.state == before
        assert np.array_equal(replay.app._viewer.frame, preview)
        assert len(replay.clicks) == 1


@pytest.mark.parametrize("phase", ["settling", "line_out", "recast"])
def test_pause_blocks_actions_and_recovers_without_a_catch(replay, phase):
    replay.start()
    if phase != "settling":
        replay.advance(3000)
        replay.observe()
    if phase == "recast":
        replay.scene("gone")
        replay.observe()
    catches = replay.state["catches"]
    replay.pause_scene()
    assert replay.observe().blocking_ui == "pause_menu"
    clicks = len(replay.clicks)
    replay.key("f8")
    replay.advance(5000)
    replay.observe()
    assert len(replay.clicks) == clicks
    assert replay.state["preview"] == "paused"
    assert "Paused" in replay.state["status"]
    replay.scene()
    replay.observe()
    assert len(replay.clicks) == clicks + 1
    replay.advance(1000)
    assert len(replay.clicks) == clicks + (2 if phase == "line_out" else 1)
    assert replay.state["catches"] == catches


def test_missing_window_geometry_change_recalibration_and_capture_recovery(replay):
    window = replay.window
    replay.window = None
    replay.start()
    assert replay.state["fishing"] is False
    assert replay.clicks == []
    assert "Could not find" in replay.state["status"]
    replay.window = window
    replay.start()
    replay.advance(3000)
    replay.observe()
    old_box = replay.capture_boxes[-1]
    replay.window = replace(window, left=218, top=130, width=1400, height=800)
    replay.scene()
    replay.advance(500)
    replay.observe()
    assert replay.capture_boxes[-1] == (218, 130, 1618, 930)
    assert replay.capture_boxes[-1] != old_box
    replay.key("f9")
    assert replay.state["status"] == "Calibrated tracking box"

    replay.capture_error = "synthetic capture failure"
    for _ in range(3):
        assert replay.observe().capture_error == "synthetic capture failure"
    assert replay.state["catches"] == 0
    assert replay.app._minecraft_window is None
    assert replay.app._fishing_roi is None
    replay.capture_error = None
    replay.advance(500)
    assert replay.observe().capture_error is None
    assert replay.state["preview"] in {"valid", "invalid"}


def test_global_escape_is_ignored(replay):
    replay.start()
    replay.key("esc")
    assert replay.state["fishing"] is True
    replay.stop()
    assert replay.state["fishing"] is False


@pytest.mark.parametrize(
    "replay",
    [
        RuntimeConfig(
            recast=DelayRange(700, 700), auto_strafe_enabled=True, audio_hints_enabled=True
        )
    ],
    indirect=True,
)
def test_movement_and_audio_options_preserve_vision_actions(replay):
    replay.key("f7")
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.audio.events.append(AudioHintEvent(12.5, 0.2, 0.5))
    replay.observe()
    assert replay.audio.started
    assert len(replay.clicks) == 1
    assert replay.state["catches"] == 0
    assert [row["event"] for row in replay.trace()].count("audio_hint") == 1

    replay.scene("gone")
    replay.observe()
    reel_at = replay.clicks[-1].time
    replay.advance(700)
    assert round(replay.clicks[-1].time - reel_at, 6) == 0.7
    downs = [action.args for action in replay.actions if action.kind == "keyDown"]
    ups = [action.args for action in replay.actions if action.kind == "keyUp"]
    assert downs and downs == ups
    movement = [row for row in replay.trace() if row["event"] == "strafe"][-1]
    assert abs(int(movement["strafe_offset_steps"])) <= 4
    assert abs(int(movement["mouse_offset_x_px"])) <= 16
    assert abs(int(movement["mouse_offset_y_px"])) <= 8


def test_disabled_audio_and_movement_do_not_start_or_emit_input(replay):
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.scene("gone")
    replay.observe()
    assert not replay.audio.started
    assert {action.kind for action in replay.actions} == {"rightClick"}


def test_recording_artifacts_survive_toggle_stop_restart_and_quit(replay):
    replay.key("f7")
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.observe()
    replay.key("f8")
    replay.key("f7")  # Drains all writes and finalizes partial mark clips.
    assert replay.state["catches"] == 0

    session = replay.log_path.parent
    images = list(session.glob("*.png"))
    clips = list(session.glob("replay-training-miss-*/*.png"))
    assert images and clips
    for path in images + clips:
        assert cv2.imread(str(path)) is not None
    for label in ("window", "debug"):
        video = cv2.VideoCapture(str(session / f"replay-{label}.mp4"))
        try:
            assert video.isOpened()
            success, frame = video.read()
            assert success and frame.size > 0
            if label == "window":
                assert frame.shape[:2] == (748, 1280)
        finally:
            video.release()

    summary = summarize_session(session / "replay-profile.csv")
    assert summary["eventCounts"]["training_reel"] == 1
    assert summary["eventCounts"]["reel"] == 1
    assert summary["eventCounts"]["cast"] == 1
    replay.stop()
    replay.key("f7")
    replay.start()
    replay.advance(3000)
    replay.observe()
    replay.close()
    replay.advance(10000)
    assert replay.root.destroyed
    assert replay.state["fishing"] is False
    state = json.loads((replay.app._window_state_path()).read_text())
    assert state["position"] == "+300+0"
