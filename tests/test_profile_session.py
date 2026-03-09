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


def test_profile_flamegraph_script_exists() -> None:
    assert Path("scripts/profile_flamegraph.sh").exists()
