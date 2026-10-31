from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_offline_commands_and_launcher_compatibility(tmp_path):
    project = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env.pop("AUTOANGLER_SESSION_LOG", None)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            str(project / "scripts" / "verify_offline.py"),
            "--work",
            str(tmp_path / "cli"),
            "--legacy",
            str(project / "auto-angler" / "auto-angler.py"),
        ],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    (tmp_path / "cli-process.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr


def test_offline_verification_refuses_existing_directory(tmp_path):
    project = Path(__file__).resolve().parents[1]
    work = tmp_path / "existing"
    work.mkdir()
    evidence = work / "commands.json"
    evidence.write_text("preserve this evidence")
    result = subprocess.run(
        [sys.executable, str(project / "scripts" / "verify_offline.py"), "--work", str(work)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert evidence.read_text() == "preserve this evidence"
