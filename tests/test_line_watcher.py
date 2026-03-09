from __future__ import annotations

from autoangler.line_watcher import LineWatcher


def test_observe_does_not_trigger_on_single_shallow_drop_by_default() -> None:
    watcher = LineWatcher(drop_ratio=0.4, min_reference_pixels=20)

    assert watcher.observe(40, active=True) is False
    assert watcher.observe(42, active=True) is False
    assert watcher.observe(14, active=True) is False


def test_observe_triggers_immediately_on_zero_pixels_by_default() -> None:
    watcher = LineWatcher(drop_ratio=0.4, min_reference_pixels=20)

    assert watcher.observe(40, active=True) is False
    assert watcher.observe(42, active=True) is False
    assert watcher.observe(0, active=True) is True


def test_observe_ignores_single_reference_spike_when_evaluating_bite() -> None:
    watcher = LineWatcher(drop_ratio=0.4, min_reference_pixels=20)

    assert watcher.observe(60, active=True) is False
    assert watcher.observe(64, active=True) is False
    assert watcher.observe(1582, active=True) is False
    assert watcher.observe(33, active=True) is False
    assert watcher.observe(46, active=True) is False
    assert watcher.trigger_pixels == 25


def test_observe_can_still_require_multiple_weak_frames_when_requested() -> None:
    watcher = LineWatcher(drop_ratio=0.4, min_frames=2, min_reference_pixels=20)

    assert watcher.observe(40, active=True) is False
    assert watcher.observe(42, active=True) is False
    assert watcher.observe(14, active=True) is False
    assert watcher.observe(10, active=True) is True


def test_observe_resets_when_inactive() -> None:
    watcher = LineWatcher(drop_ratio=0.4, min_frames=2, min_reference_pixels=20)

    watcher.observe(40, active=True)
    watcher.observe(42, active=True)
    watcher.observe(10, active=False)

    assert watcher.observe(15, active=True) is False
