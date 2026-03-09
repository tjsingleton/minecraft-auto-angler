from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DelayRange:
    minimum_ms: int
    maximum_ms: int

    def __post_init__(self) -> None:
        if self.minimum_ms > self.maximum_ms:
            raise ValueError("minimum_ms must be <= maximum_ms")
        if self.minimum_ms < 0 or self.maximum_ms < 0:
            raise ValueError("delay bounds must be >= 0")

    def choose(self, *, rng: random.Random | None = None) -> int:
        generator = rng or random.Random()
        return generator.randint(self.minimum_ms, self.maximum_ms)


@dataclass(frozen=True)
class RuntimeConfig:
    cast_settle: DelayRange = field(
        default_factory=lambda: DelayRange(minimum_ms=3000, maximum_ms=3000)
    )
    recast: DelayRange = field(
        default_factory=lambda: DelayRange(minimum_ms=300, maximum_ms=1000)
    )
    audio_hints_enabled: bool = False
    auto_strafe_enabled: bool = True

    def metadata(self) -> dict[str, int]:
        return {
            "cast_settle_min_ms": self.cast_settle.minimum_ms,
            "cast_settle_max_ms": self.cast_settle.maximum_ms,
            "recast_min_ms": self.recast.minimum_ms,
            "recast_max_ms": self.recast.maximum_ms,
            "audio_hints_enabled": int(self.audio_hints_enabled),
            "auto_strafe_enabled": int(self.auto_strafe_enabled),
        }


def build_runtime_config(args: Any) -> RuntimeConfig:
    return RuntimeConfig(
        cast_settle=DelayRange(
            minimum_ms=int(getattr(args, "cast_settle_min_ms", 3000)),
            maximum_ms=int(getattr(args, "cast_settle_max_ms", 3000)),
        ),
        recast=DelayRange(
            minimum_ms=int(getattr(args, "recast_min_ms", 300)),
            maximum_ms=int(getattr(args, "recast_max_ms", 1000)),
        ),
        audio_hints_enabled=bool(getattr(args, "audio_hints", False)),
        auto_strafe_enabled=bool(getattr(args, "auto_strafe", True)),
    )
