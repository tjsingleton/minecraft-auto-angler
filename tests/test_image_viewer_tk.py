from __future__ import annotations

from autoangler.image_viewer_tk import fit_within


def test_fit_within_preserves_size_when_already_small() -> None:
    assert fit_within(200, 100, 320, 320) == (200, 100)


def test_fit_within_scales_down_wide_image() -> None:
    assert fit_within(640, 320, 320, 320) == (320, 160)


def test_fit_within_scales_down_tall_image() -> None:
    assert fit_within(320, 640, 320, 320) == (160, 320)
