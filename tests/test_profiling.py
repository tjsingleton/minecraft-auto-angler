from __future__ import annotations

from autoangler.profiling import RollingProfiler, TickProfile


def test_rolling_profiler_computes_stage_averages() -> None:
    profiler = RollingProfiler(capacity=3)

    profiler.add(
        TickProfile(
            total_ms=100.0,
            capture_ms=70.0,
            detect_ms=10.0,
            preview_ms=15.0,
            record_ms=5.0,
        )
    )
    profiler.add(
        TickProfile(
            total_ms=80.0,
            capture_ms=50.0,
            detect_ms=15.0,
            preview_ms=10.0,
            record_ms=5.0,
        )
    )

    summary = profiler.summary()

    assert summary.avg_total_ms == 90.0
    assert summary.avg_capture_ms == 60.0
    assert summary.avg_detect_ms == 12.5
    assert summary.avg_preview_ms == 12.5
    assert summary.avg_record_ms == 5.0
