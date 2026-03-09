from __future__ import annotations

import argparse

from autoangler.gui_tk import AutoFishTkApp
from autoangler.logging_utils import configure_logging
from autoangler.runtime_config import build_runtime_config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AutoAngler.")
    parser.add_argument("--cast-settle-min-ms", type=int, default=3000)
    parser.add_argument("--cast-settle-max-ms", type=int, default=3000)
    parser.add_argument("--recast-min-ms", type=int, default=300)
    parser.add_argument("--recast-max-ms", type=int, default=1000)
    parser.add_argument("--audio-hints", action="store_true")
    parser.add_argument("--no-auto-strafe", action="store_false", dest="auto_strafe")
    parser.set_defaults(auto_strafe=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        runtime_config = build_runtime_config(args)
        log_path = configure_logging()
        import logging

        logging.getLogger(__name__).info(
            "Starting AutoAngler%s cast=%sms-%sms recast=%sms-%sms audio_hints=%s auto_strafe=%s",
            f" (log: {log_path})" if log_path is not None else "",
            runtime_config.cast_settle.minimum_ms,
            runtime_config.cast_settle.maximum_ms,
            runtime_config.recast.minimum_ms,
            runtime_config.recast.maximum_ms,
            runtime_config.audio_hints_enabled,
            runtime_config.auto_strafe_enabled,
        )
        AutoFishTkApp(runtime_config=runtime_config).run()
        return 0
    except ModuleNotFoundError as exc:
        if exc.name in {"_tkinter", "tkinter"}:
            raise SystemExit(
                "Tkinter is not available in this Python build.\n\n"
                "Install a Python distribution with Tk support (or rebuild Python with Tk), "
                "then re-run:\n"
                "  uv run python -m autoangler\n"
            ) from exc
        raise
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
