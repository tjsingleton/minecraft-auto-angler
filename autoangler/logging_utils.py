from __future__ import annotations

import logging
import os
from pathlib import Path
from time import strftime


def build_session_log_path(log_dir: Path, session_name: str) -> Path:
    return log_dir / "sessions" / f"{session_name}.log"


def configure_logging() -> Path | None:
    """
    Configure console + file logging.

    Returns the log file path if file logging was configured.
    """

    level_name = os.environ.get("AUTOANGLER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Keep third-party debug noise down (Pillow gets very chatty at DEBUG).
    if os.environ.get("AUTOANGLER_LOG_PIL", "").strip() != "1":
        logging.getLogger("PIL").setLevel(max(level, logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        root_logger.addHandler(console)

    try:
        log_dir = Path.home() / ".autoangler"
        log_dir.mkdir(parents=True, exist_ok=True)
        session_name = strftime("%Y%m%d-%H%M%S")
        log_path = build_session_log_path(log_dir, session_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        for handler in list(root_logger.handlers):
            if isinstance(handler, logging.FileHandler):
                root_logger.removeHandler(handler)
                handler.close()

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        return log_path
    except Exception:
        return None
