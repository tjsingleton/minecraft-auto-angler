from __future__ import annotations

from pathlib import Path

from autoangler.profile_session import summarize_profile


def test_summarize_profile_reports_capture_as_top_stage(tmp_path: Path) -> None:
    profile_csv = tmp_path / "profile.csv"
    profile_csv.write_text(
        (
            "time_s,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,"
            "record_ms,vision_age_ms,vision_dropped_frames,record_queue_depth,"
            "record_dropped_frames,line_pixels,trigger_pixels\n"
            "1,1,1,400,350,20,20,10,8,1,2,3,10,5\n"
        ),
        encoding="utf-8",
    )

    summary = summarize_profile(profile_csv)

    assert summary["avg_total_ms"] == 400.0
    assert summary["avg_capture_ms"] == 350.0
    assert summary["avg_vision_age_ms"] == 8.0
    assert summary["avg_record_queue_depth"] == 2.0
    assert summary["max_vision_dropped_frames"] == 1
    assert summary["top_stage"] == "capture"


def test_summarize_session_tolerates_new_movement_fields(tmp_path: Path) -> None:
    profile_csv = tmp_path / "20260309-120000-profile.csv"
    trace_csv = tmp_path / "20260309-120000-trace.csv"
    profile_csv.write_text(
        (
            "time_s,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,"
            "record_ms,vision_age_ms,vision_dropped_frames,record_queue_depth,"
            "record_dropped_frames,line_pixels,trigger_pixels\n"
            "1,1,1,400,350,20,20,10,8,1,2,3,10,5\n"
        ),
        encoding="utf-8",
    )
    trace_csv.write_text(
        (
            "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,"
            "bite_detected,cast_settle_min_ms,cast_settle_max_ms,recast_min_ms,recast_max_ms,"
            "audio_hints_enabled,auto_strafe_enabled,scheduled_delay_ms,audio_hint_rms,"
            "audio_hint_peak,strafe_direction,strafe_duration_ms,strafe_offset_steps,"
            "mouse_dx_px,mouse_dy_px,mouse_offset_x_px,mouse_offset_y_px,source,"
            "training_label,rod_in_hand,catch_count\n"
            "1.0,strafe,1,1,10,5,2,1,2800,3200,300,1000,1,1,,,,left,180,2,4,-2,8,-4,auto_strafe,,1,1\n"
        ),
        encoding="utf-8",
    )

    from autoangler.profile_session import summarize_session

    summary = summarize_session(profile_csv)

    assert summary["triggerSequence"][0]["strafeOffsetSteps"] == 2
    assert summary["triggerSequence"][0]["mouseDxPx"] == 4
    assert summary["triggerSequence"][0]["mouseOffsetXPx"] == 8


def test_profile_flamegraph_script_exists() -> None:
    assert Path("scripts/profile_flamegraph.sh").exists()
