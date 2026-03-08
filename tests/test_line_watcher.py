from __future__ import annotations

from autoangler.line_watcher import LineWatcher


def test_observe_triggers_after_consecutive_line_drop() -> None:
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
