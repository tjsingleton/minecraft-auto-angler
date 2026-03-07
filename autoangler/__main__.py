from __future__ import annotations


def main() -> None:
    try:
        from autoangler.logging_utils import configure_logging

        log_path = configure_logging()

        import logging

        from autoangler.gui_tk import AutoFishTkApp

        logging.getLogger(__name__).info(
            "Starting AutoAngler%s",
            f" (log: {log_path})" if log_path is not None else "",
        )
        AutoFishTkApp().run()
    except ModuleNotFoundError as exc:
        if exc.name in {"_tkinter", "tkinter"}:
            raise SystemExit(
                "Tkinter is not available in this Python build.\n\n"
                "Install a Python distribution with Tk support (or rebuild Python with Tk), "
                "then re-run:\n"
                "  uv run python -m autoangler\n"
            ) from exc
        raise


if __name__ == "__main__":
    main()
