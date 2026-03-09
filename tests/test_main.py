from __future__ import annotations

from autoangler import __main__
from autoangler.runtime_config import DelayRange, RuntimeConfig


def test_parse_args_reads_timing_ranges_without_lab_profile() -> None:
    args = __main__.parse_args(
        [
            "--cast-settle-min-ms",
            "2800",
            "--cast-settle-max-ms",
            "3200",
            "--recast-min-ms",
            "350",
            "--recast-max-ms",
            "900",
            "--audio-hints",
        ]
    )

    assert not hasattr(args, "lab_profile")
    assert args.cast_settle_min_ms == 2800
    assert args.cast_settle_max_ms == 3200
    assert args.recast_min_ms == 350
    assert args.recast_max_ms == 900
    assert args.audio_hints is True


def test_parse_args_uses_randomized_recast_defaults() -> None:
    args = __main__.parse_args([])

    assert args.recast_min_ms == 300
    assert args.recast_max_ms == 1000


def test_main_builds_runtime_config_and_runs_app(monkeypatch) -> None:
    calls: list[RuntimeConfig] = []

    monkeypatch.setattr(__main__, "configure_logging", lambda: None)

    class FakeApp:
        def __init__(self, *, runtime_config: RuntimeConfig) -> None:
            calls.append(runtime_config)

        def run(self) -> None:
            return None

    monkeypatch.setattr(__main__, "AutoFishTkApp", FakeApp)

    exit_code = __main__.main(
        [
            "--cast-settle-min-ms",
            "2800",
            "--cast-settle-max-ms",
            "3200",
            "--recast-min-ms",
            "350",
            "--recast-max-ms",
            "900",
            "--audio-hints",
        ]
    )

    assert exit_code == 0
    assert calls == [
        RuntimeConfig(
            cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
            recast=DelayRange(minimum_ms=350, maximum_ms=900),
            audio_hints_enabled=True,
            auto_strafe_enabled=True,
        )
    ]


def test_main_exits_cleanly_for_invalid_delay_range() -> None:
    try:
        __main__.main(
            [
                "--cast-settle-min-ms",
                "3200",
                "--cast-settle-max-ms",
                "2800",
            ]
        )
    except SystemExit as exc:
        assert str(exc) == "minimum_ms must be <= maximum_ms"
    else:
        raise AssertionError("expected SystemExit")
