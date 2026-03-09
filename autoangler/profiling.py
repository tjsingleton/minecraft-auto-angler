from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TickProfile:
    total_ms: float
    capture_ms: float
    detect_ms: float
    preview_ms: float
    record_ms: float


@dataclass(frozen=True)
class ProfileSummary:
    avg_total_ms: float
    avg_capture_ms: float
    avg_detect_ms: float
    avg_preview_ms: float
    avg_record_ms: float


class RollingProfiler:
    def __init__(self, *, capacity: int = 60) -> None:
        self._profiles: deque[TickProfile] = deque(maxlen=max(1, capacity))

    def add(self, profile: TickProfile) -> None:
        self._profiles.append(profile)

    def summary(self) -> ProfileSummary:
        if not self._profiles:
            return ProfileSummary(
                avg_total_ms=0.0,
                avg_capture_ms=0.0,
                avg_detect_ms=0.0,
                avg_preview_ms=0.0,
                avg_record_ms=0.0,
            )

        count = float(len(self._profiles))
        return ProfileSummary(
            avg_total_ms=sum(p.total_ms for p in self._profiles) / count,
            avg_capture_ms=sum(p.capture_ms for p in self._profiles) / count,
            avg_detect_ms=sum(p.detect_ms for p in self._profiles) / count,
            avg_preview_ms=sum(p.preview_ms for p in self._profiles) / count,
            avg_record_ms=sum(p.record_ms for p in self._profiles) / count,
        )
