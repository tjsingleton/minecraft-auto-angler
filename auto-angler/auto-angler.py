from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    # This file is a legacy launcher to keep the original README command working:
    #   cd auto-angler && uv run python auto-angler.py
    #
    # It runs from inside the `auto-angler/` directory, so we add the repo root to sys.path
    # to import the real package implementation in `autoangler/`.
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))

    from autoangler.__main__ import main as real_main

    real_main()


if __name__ == "__main__":
    main()
