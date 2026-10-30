"""Exercise real offline CLIs with temporary fixtures, from source or an installed wheel."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def verify(work: Path, *, legacy: Path | None = None) -> None:
    work.mkdir(parents=True, exist_ok=True)
    home = work / "home"
    home.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("AUTOANGLER_")}
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    python = sys.executable
    commands = []

    def run(*args: str, success: bool = True) -> str:
        result = subprocess.run(args, cwd=work, env=env, capture_output=True, text=True, timeout=20)
        commands.append(
            {
                "args": args,
                "exit": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if success:
            assert result.returncode == 0, commands[-1]
        else:
            assert result.returncode != 0, commands[-1]
        return result.stdout if success else result.stderr

    launchers = [(python, "-m", "autoangler"), (str(Path(python).with_name("autoangler")),)]
    if legacy is not None:
        launchers.append((python, str(legacy.resolve())))
    for launcher in launchers:
        help_text = run(*launcher, "--help")
        assert "--cast-settle-min-ms" in help_text and "--no-auto-strafe" in help_text
        error = run(
            *launcher, "--cast-settle-min-ms", "3200", "--cast-settle-max-ms", "2800", success=False
        )
        assert "minimum_ms must be <= maximum_ms" in error
        assert "unrecognized arguments" in run(*launcher, "--unknown-option", success=False)

    image = np.full((120, 120), 180, dtype=np.uint8)
    cv2.line(image, (50, 40), (70, 80), 0, thickness=2)
    image_path = work / "frame.png"
    assert cv2.imwrite(str(image_path), image)
    run(python, "-m", "autoangler.analyze_image", str(image_path), "--output-dir", str(work))
    analysis = json.loads((work / "frame-analysis.json").read_text())
    assert analysis["tracking_box"] == [20, 20, 100, 100]
    assert analysis["line_pixels"] > 0 and analysis["candidate_bbox"] is not None
    for kind in ("crop", "mask", "overlay"):
        assert cv2.imread(str(work / f"frame-analysis-{kind}.png")) is not None

    profile = work / "session-profile.csv"
    profile.write_text(
        "time_s,is_fishing,is_line_out,total_ms,capture_ms,detect_ms,preview_ms,record_ms\n"
        "1,1,1,400,350,20,20,10\n"
    )
    trace = work / "session-trace.csv"
    trace.write_text("time_s,event,source,catch_count\n1,cast,manual,0\n2,reel,vision,1\n")
    summary = json.loads(run(python, "-m", "autoangler.profile_session", str(profile)))
    assert summary["avg_total_ms"] == 400
    assert summary["avg_capture_ms"] == 350 and summary["top_stage"] == "capture"
    assert summary["eventCounts"] == {"cast": 1, "reel": 1}
    assert [item["source"] for item in summary["triggerSequence"]] == ["manual", "vision"]

    log = work / "session.log"
    records = []
    for index, rows in enumerate((5, 5, 0)):
        frame = np.full((20, 20), 180, dtype=np.uint8)
        frame[:rows] = 0
        path = work / f"session-recording-{index:02}.png"
        assert cv2.imwrite(str(path), frame)
        records.append(
            f"2026-01-01 00:00:0{index + 1} INFO autoangler.gui_tk: Saved screenshot to {path}"
        )
        if index == 1:
            records.append("2026-01-01 00:00:02 INFO autoangler.gui_tk: Manual bite mark")
    log.write_text("\n".join(records) + "\n")
    experiments = work / "experiments.jsonld"
    for _ in range(2):
        result = json.loads(
            run(
                python,
                "-m",
                "autoangler.experiment_harness",
                str(log),
                "--box",
                "0,0,20,20",
                "--strategy",
                "absolute",
                "--threshold",
                "32",
                "--pre-frames",
                "0",
                "--post-frames",
                "1",
                "--experiment-log",
                str(experiments),
            )
        )
        assert result["@type"] == "ExperimentRun"
        assert result["linePixels"] == [100, 100, 0]
        assert result["detectionIndices"] == [2]
        assert result["hitCount"] == 1 and result["missCount"] == 0
        assert result["falsePositiveCount"] == 0
    entries = [json.loads(line) for line in experiments.read_text().splitlines()]
    assert len(entries) == 2 and all(entry["hitCount"] == 1 for entry in entries)
    assert not (home / ".autoangler").exists()
    print(
        "Offline CLI verification passed: launchers, image analysis, profile, "
        "replay, append-only writes"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--legacy", type=Path)
    args = parser.parse_args()
    verify(args.work.resolve(), legacy=args.legacy)
