from __future__ import annotations

import subprocess
from pathlib import Path


def test_sessions_clean_removes_session_and_screenshot_artifacts(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    makefile_path = repo_root / "Makefile"

    sessions_dir = tmp_path / "sessions"
    screenshots_dir = tmp_path / "screenshots"
    sessions_dir.mkdir()
    screenshots_dir.mkdir()

    (sessions_dir / "session.log").write_text("log")
    (sessions_dir / "session-recording-00.png").write_text("image")
    (sessions_dir / "session-trace.csv").write_text("trace")
    (screenshots_dir / "Screenshot 1.png").write_text("image")

    result = subprocess.run(
        ["make", "-f", str(makefile_path), "sessions:clean"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert sessions_dir.exists()
    assert screenshots_dir.exists()
    assert list(sessions_dir.iterdir()) == []
    assert list(screenshots_dir.iterdir()) == []
