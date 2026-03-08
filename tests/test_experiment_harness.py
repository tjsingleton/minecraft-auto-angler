from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from autoangler.experiment_harness import run_experiment


def _write_frame(path: Path, black_rows: int) -> None:
    frame = np.full((20, 20), 200, dtype=np.uint8)
    frame[:black_rows, :] = 0
    cv2.imwrite(str(path), frame)


def test_run_experiment_appends_jsonld_results(tmp_path: Path) -> None:
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    log_path = session_dir / "20260307-230000.log"
    trace_path = session_dir / "20260307-230000-trace.csv"
    experiment_log = tmp_path / "experiment-log.jsonld"

    frame_paths = [
        session_dir / "20260307-230000-recording-00.png",
        session_dir / "20260307-230000-recording-01.png",
        session_dir / "20260307-230000-recording-02.png",
        session_dir / "20260307-230000-recording-03.png",
    ]
    _write_frame(frame_paths[0], 5)
    _write_frame(frame_paths[1], 5)
    _write_frame(frame_paths[2], 1)
    _write_frame(frame_paths[3], 1)

    log_path.write_text(
        "\n".join(
            [
                f"2026-03-07 23:00:01 INFO autoangler.gui_tk: Saved screenshot to {frame_paths[0]}",
                f"2026-03-07 23:00:02 INFO autoangler.gui_tk: Saved screenshot to {frame_paths[1]}",
                "2026-03-07 23:00:02 INFO autoangler.gui_tk: Manual bite mark",
                f"2026-03-07 23:00:03 INFO autoangler.gui_tk: Saved screenshot to {frame_paths[2]}",
                f"2026-03-07 23:00:04 INFO autoangler.gui_tk: Saved screenshot to {frame_paths[3]}",
                "2026-03-07 23:05:00 INFO autoangler.gui_tk: Manual bite mark",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    trace_path.write_text(
        "\n".join(
            [
                "time_s,event,is_fishing,is_line_out,line_pixels,trigger_pixels,weak_frames,bite_detected",
                "1.0,mark,1,1,100,40,0,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    first = run_experiment(
        session_log=log_path,
        session_trace=trace_path,
        tracking_box=(0, 0, 20, 20),
        strategy="absolute",
        threshold=32,
        experiment_log=experiment_log,
        pre_frames=0,
        post_frames=2,
    )
    second = run_experiment(
        session_log=log_path,
        session_trace=trace_path,
        tracking_box=(0, 0, 20, 20),
        strategy="absolute",
        threshold=32,
        experiment_log=experiment_log,
        pre_frames=0,
        post_frames=2,
    )

    assert first["markCount"] == 1
    assert first["hitCount"] == 1
    assert first["missCount"] == 0
    assert first["falsePositiveCount"] == 0
    assert first["detectionIndices"] == [3]
    assert second["hitCount"] == 1

    lines = experiment_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first_line = json.loads(lines[0])
    assert first_line["@type"] == "ExperimentRun"
    assert first_line["strategy"] == "absolute"
    assert first_line["trackingBox"] == [0, 0, 20, 20]
