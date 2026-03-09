from __future__ import annotations

from pathlib import Path

import pytest

from autoangler.audio_probe import (
    AudioHintEvent,
    AudioSplashDetector,
    AudioStats,
    build_capture_command,
    build_compile_command,
    compiled_helper_path,
    parse_audio_stats_line,
    parse_bite_candidate_line,
)


def test_parse_audio_stats_line_reads_helper_json() -> None:
    stats = parse_audio_stats_line(
        '{"timestamp": 12.5, "rms": 0.031, "peak": 0.19, "frameCount": 2048}'
    )

    assert stats == AudioStats(timestamp=12.5, rms=0.031, peak=0.19, frame_count=2048)


def test_parse_audio_stats_line_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError, match="audio stats"):
        parse_audio_stats_line("not-json")


def test_audio_splash_detector_triggers_after_strong_onset() -> None:
    detector = AudioSplashDetector(
        min_samples=3,
        rms_ratio_threshold=2.5,
        peak_threshold=0.2,
        cooldown_s=0.75,
    )

    assert (
        detector.observe(AudioStats(timestamp=0.0, rms=0.02, peak=0.04, frame_count=1024))
        is False
    )
    assert (
        detector.observe(AudioStats(timestamp=0.1, rms=0.025, peak=0.05, frame_count=1024))
        is False
    )
    assert (
        detector.observe(AudioStats(timestamp=0.2, rms=0.03, peak=0.06, frame_count=1024))
        is False
    )

    assert (
        detector.observe(AudioStats(timestamp=0.3, rms=0.09, peak=0.24, frame_count=1024))
        is True
    )


def test_audio_splash_detector_respects_cooldown() -> None:
    detector = AudioSplashDetector(
        min_samples=2,
        rms_ratio_threshold=2.0,
        peak_threshold=0.18,
        cooldown_s=1.0,
    )

    assert (
        detector.observe(AudioStats(timestamp=0.0, rms=0.03, peak=0.05, frame_count=1024))
        is False
    )
    assert (
        detector.observe(AudioStats(timestamp=0.1, rms=0.03, peak=0.05, frame_count=1024))
        is False
    )
    assert (
        detector.observe(AudioStats(timestamp=0.2, rms=0.08, peak=0.22, frame_count=1024))
        is True
    )
    assert (
        detector.observe(AudioStats(timestamp=0.5, rms=0.09, peak=0.25, frame_count=1024))
        is False
    )
    assert (
        detector.observe(AudioStats(timestamp=1.3, rms=0.09, peak=0.25, frame_count=1024))
        is True
    )


def test_compiled_helper_path_strips_swift_suffix() -> None:
    assert compiled_helper_path(Path("/tmp/macos_minecraft_audio_capture.swift")) == Path(
        "/tmp/macos_minecraft_audio_capture"
    )


def test_build_compile_command_targets_real_binary() -> None:
    command = build_compile_command(
        helper_path=Path("/tmp/macos_minecraft_audio_capture.swift"),
        binary_path=Path("/tmp/macos_minecraft_audio_capture"),
    )

    assert command == [
        "swiftc",
        "-O",
        "/tmp/macos_minecraft_audio_capture.swift",
        "-o",
        "/tmp/macos_minecraft_audio_capture",
    ]


def test_build_capture_command_points_to_compiled_helper() -> None:
    command = build_capture_command(
        binary_path=Path("/tmp/macos_minecraft_audio_capture"),
        title_hint="Minecraft",
    )

    assert command == [
        "/tmp/macos_minecraft_audio_capture",
        "--title-hint",
        "Minecraft",
    ]


def test_parse_bite_candidate_line_reads_probe_output() -> None:
    event = parse_bite_candidate_line("BITE_CANDIDATE t=12.500 rms=0.0310 peak=0.1900")

    assert event == AudioHintEvent(timestamp=12.5, rms=0.031, peak=0.19)
