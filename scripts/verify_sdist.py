"""Extract a source distribution, run locked checks, rebuild, and verify its wheel."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from verification_support import verification_directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--work", type=Path, help="Retain evidence in a new directory")
    args = parser.parse_args()
    archive = args.archive.resolve(strict=True)
    with verification_directory("autoangler-sdist-", args.work) as work:
        source = work / "source"
        with tarfile.open(archive) as handle:
            handle.extractall(source, filter="data")
        roots = list(source.iterdir())
        assert len(roots) == 1 and roots[0].is_dir()
        project = roots[0]
        env = os.environ.copy()
        for name in (
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "UV_PROJECT_ENVIRONMENT",
            "AUTOANGLER_INTEGRATION",
        ):
            env.pop(name, None)
        env["HOME"] = str(work / "home")
        (work / "home").mkdir()
        reports = work / "reports"
        reports.mkdir()

        def run(*command: str) -> None:
            subprocess.run(command, cwd=project, env=env, check=True, timeout=300)

        run("uv", "sync", "--locked", "--group", "dev", "--python", sys.executable)
        run("uv", "run", "--locked", "ruff", "check", ".")
        run("uv", "run", "--locked", "ruff", "format", "--check", ".")
        run(
            "uv",
            "run",
            "--locked",
            "pytest",
            "--basetemp",
            str(reports / "tests"),
            "--junitxml",
            str(reports / "pytest.xml"),
        )
        run("uv", "build")
        wheels = list((project / "dist").glob("*.whl"))
        assert len(wheels) == 1
        run(
            "uv",
            "run",
            "--locked",
            "python",
            "scripts/smoke_wheel.py",
            str(wheels[0]),
            "--work",
            str(work / "wheel"),
        )
        print("Fresh source-distribution checks and rebuilt installed wheel passed")


if __name__ == "__main__":
    main()
