"""Install and exercise a wheel outside the checkout without starting desktop automation."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path

from verification_support import verification_directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--work", type=Path, help="Retain evidence in a new directory")
    args = parser.parse_args()
    wheel = args.wheel.resolve(strict=True)
    project = Path(__file__).resolve().parents[1]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "autoangler/macos_minecraft_audio_capture" not in names
        assert "autoangler/macos_minecraft_audio_capture.swift" in names
        assert not any(name.endswith((".DS_Store", ".pyc")) for name in names)

    with verification_directory("autoangler-wheel-", args.work) as work:
        environment = work / "venv"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("VIRTUAL_ENV", None)
        home = work / "home"
        home.mkdir()
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        for name in list(env):
            if name.startswith("AUTOANGLER_"):
                env.pop(name)

        def run(*command: str) -> None:
            subprocess.run(command, cwd=work, env=env, check=True)

        run("uv", "venv", "--python", sys.executable, str(environment))
        binary = environment / ("Scripts" if sys.platform == "win32" else "bin")
        python = str(binary / "python")
        constraints = work / "constraints.txt"
        run(
            "uv",
            "export",
            "--project",
            str(project),
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
            "--output-file",
            str(constraints),
        )
        run("uv", "pip", "install", "--python", python, "-c", str(constraints), str(wheel))
        run(str(binary / "autoangler"), "--help")
        for module in ("analyze_image", "profile_session", "experiment_harness", "audio_probe"):
            run(python, "-m", f"autoangler.{module}", "--help")
        run(
            python,
            "-c",
            "from importlib.resources import files; "
            "import autoangler, sys; "
            "assert str(autoangler.__file__).startswith(sys.prefix); "
            "assets = files('autoangler.assets'); "
            "names = ('minecraft_cursor.png', 'fishing_rod_slot_template.png', "
            "'pause_menu_options_template.png', 'Cod.gif', 'cod_icon.png'); "
            "assert all(assets.joinpath(name).is_file() for name in names); "
            "print('Installed package and all templates verified')",
        )
        run(python, str(project / "scripts" / "verify_offline.py"), "--work", str(work / "offline"))


if __name__ == "__main__":
    main()
