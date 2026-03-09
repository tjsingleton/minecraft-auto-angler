from __future__ import annotations

import random

import pytest

from autoangler.runtime_config import DelayRange, RuntimeConfig, build_runtime_config


def test_delay_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="minimum_ms"):
        DelayRange(minimum_ms=400, maximum_ms=399)


def test_delay_range_choose_stays_within_configured_bounds() -> None:
    delay_range = DelayRange(minimum_ms=10, maximum_ms=12)
    rng = random.Random(7)

    values = {delay_range.choose(rng=rng) for _ in range(20)}

    assert values <= {10, 11, 12}
    assert values >= {10, 11}


def test_build_runtime_config_maps_cli_args() -> None:
    class Args:
        cast_settle_min_ms = 2800
        cast_settle_max_ms = 3200
        recast_min_ms = 350
        recast_max_ms = 900
        audio_hints = True
        auto_strafe = False

    config = build_runtime_config(Args())

    assert config == RuntimeConfig(
        cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
        recast=DelayRange(minimum_ms=350, maximum_ms=900),
        audio_hints_enabled=True,
        auto_strafe_enabled=False,
    )


def test_runtime_config_metadata_reports_ranges_and_audio_setting() -> None:
    config = RuntimeConfig(
        cast_settle=DelayRange(minimum_ms=2800, maximum_ms=3200),
        recast=DelayRange(minimum_ms=350, maximum_ms=900),
        audio_hints_enabled=True,
        auto_strafe_enabled=True,
    )

    assert config.metadata() == {
        "cast_settle_min_ms": 2800,
        "cast_settle_max_ms": 3200,
        "recast_min_ms": 350,
        "recast_max_ms": 900,
        "audio_hints_enabled": 1,
        "auto_strafe_enabled": 1,
    }
