from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOANGLER_INTEGRATION") != "1",
    reason="Set AUTOANGLER_INTEGRATION=1 to run real Tk wiring with fake desktop boundaries.",
)


def test_real_tk_startup_hotkey_dispatch_menus_preview_and_close(tmp_path):
    project = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("AUTOANGLER_SESSION_LOG", None)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "tests.tk_runtime_scenario", str(tmp_path / "tk")],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    (tmp_path / "tk-process.txt").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "tk" / "tk-result.json").is_file()
