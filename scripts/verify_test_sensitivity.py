"""Prove key replay assertions catch three regressions in disposable source copies."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from verification_support import verification_directory

CASES = (
    (
        "scheduled-action-guard",
        "autoangler/gui_tk.py",
        "if generation != self._scheduled_action_generation:",
        "if False:",
        "tests/test_runtime_replay.py::test_stop_invalidates_pending_actions_and_restart_results[recast]",
    ),
    (
        "stale-epoch-guard",
        "autoangler/gui_tk.py",
        "if result.epoch != self._vision_epoch:",
        "if False:",
        "tests/test_runtime_replay.py::test_duplicate_older_and_stale_results_have_no_effect",
    ),
    (
        "newest-pending-frame",
        "autoangler/async_pipeline.py",
        "            self._pending = request\n",
        "            if self._pending is None:\n                self._pending = request\n",
        "tests/test_worker_lifecycle.py::test_real_vision_worker_keeps_newest_pending_frame",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, help="Retain evidence in a new directory")
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("AUTOANGLER_INTEGRATION", None)
    with verification_directory("autoangler-sensitivity-", args.work) as work:
        baseline = work / "baseline"
        baseline.mkdir()
        for name in ("autoangler", "tests"):
            shutil.copytree(
                project / name,
                baseline / name,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        shutil.copy2(project / "pyproject.toml", baseline / "pyproject.toml")
        summaries = []

        def run(directory: Path, tests: list[str], expected: int) -> None:
            home = directory / "home"
            home.mkdir()
            test_env = dict(env, HOME=str(home), USERPROFILE=str(home))
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import autoangler; "
                    "assert Path(autoangler.__file__).is_relative_to(Path.cwd())",
                ],
                cwd=directory,
                env=test_env,
                check=True,
                timeout=10,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    *tests,
                    "-q",
                    "--tb=short",
                    "--basetemp",
                    str(directory / "artifacts"),
                    "--junitxml",
                    str(directory / "pytest.xml"),
                ],
                cwd=directory,
                env=test_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            (directory / "pytest.txt").write_text(result.stdout + result.stderr)
            assert result.returncode == expected, result.stdout + result.stderr
            report = ET.parse(directory / "pytest.xml")
            assert not report.findall(".//error"), "Test setup/teardown failed"
            failures = report.findall(".//failure")
            assert len(failures) == (1 if expected else 0)
            if failures:
                message = failures[0].get("message", "")
                assert message.startswith("assert ") or "AssertionError" in message, message

        run(baseline, [case[4] for case in CASES], 0)
        # Each experiment starts from the same unmodified source snapshot.
        for name, file, original, replacement, test in CASES:
            directory = work / name
            directory.mkdir()
            for item in ("autoangler", "tests"):
                shutil.copytree(
                    baseline / item,
                    directory / item,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                )
            shutil.copy2(baseline / "pyproject.toml", directory / "pyproject.toml")
            path = directory / file
            source = path.read_text()
            assert source.count(original) == 1, f"Mutation anchor changed: {name}"
            path.write_text(source.replace(original, replacement, 1))
            run(directory, [test], 1)
            summaries.append({"regression": name, "test": test, "caught": True})
            print(f"Caught intentional regression: {name}", flush=True)
        (work / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    main()
