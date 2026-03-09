from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, TextIO

logger = logging.getLogger(__name__)
BITE_CANDIDATE_PATTERN = re.compile(
    r"^BITE_CANDIDATE t=(?P<timestamp>\d+(?:\.\d+)?) "
    r"rms=(?P<rms>\d+(?:\.\d+)?) peak=(?P<peak>\d+(?:\.\d+)?)$"
)


@dataclass(frozen=True)
class AudioStats:
    timestamp: float
    rms: float
    peak: float
    frame_count: int


@dataclass(frozen=True)
class AudioHintEvent:
    timestamp: float
    rms: float
    peak: float


class AudioSplashDetector:
    def __init__(
        self,
        *,
        min_samples: int = 8,
        rms_ratio_threshold: float = 2.8,
        peak_threshold: float = 0.2,
        cooldown_s: float = 1.0,
        baseline_window: int = 24,
    ) -> None:
        self._min_samples = min_samples
        self._rms_ratio_threshold = rms_ratio_threshold
        self._peak_threshold = peak_threshold
        self._cooldown_s = cooldown_s
        self._history: deque[float] = deque(maxlen=baseline_window)
        self._last_trigger_at = float("-inf")

    def observe(self, stats: AudioStats) -> bool:
        baseline_rms = self._baseline_rms
        enough_history = len(self._history) >= self._min_samples
        over_ratio = baseline_rms > 0 and stats.rms >= baseline_rms * self._rms_ratio_threshold
        over_peak = stats.peak >= self._peak_threshold
        out_of_cooldown = (stats.timestamp - self._last_trigger_at) >= self._cooldown_s

        triggered = enough_history and over_ratio and over_peak and out_of_cooldown

        # Keep the baseline focused on ambient audio instead of letting splash-sized spikes
        # ratchet the threshold upward and hide the next bite.
        if not (enough_history and over_ratio and over_peak):
            self._history.append(stats.rms)
        if triggered:
            self._last_trigger_at = stats.timestamp
        return triggered

    @property
    def _baseline_rms(self) -> float:
        if not self._history:
            return 0.0
        return sum(self._history) / len(self._history)


def parse_audio_stats_line(line: str) -> AudioStats:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid audio stats line: expected JSON audio stats") from exc

    try:
        return AudioStats(
            timestamp=float(payload["timestamp"]),
            rms=float(payload["rms"]),
            peak=float(payload["peak"]),
            frame_count=int(payload["frameCount"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid audio stats line: missing required audio stats fields") from exc


def compiled_helper_path(helper_path: Path) -> Path:
    return helper_path.with_suffix("")


def build_compile_command(helper_path: Path, binary_path: Path) -> list[str]:
    return ["swiftc", "-O", str(helper_path), "-o", str(binary_path)]


def build_capture_command(binary_path: Path, title_hint: str | None) -> list[str]:
    command = [str(binary_path)]
    if title_hint:
        command.extend(["--title-hint", title_hint])
    return command


def default_helper_path() -> Path:
    return Path(__file__).with_name("macos_minecraft_audio_capture.swift")


def ensure_compiled_helper(helper_path: Path) -> Path:
    binary_path = compiled_helper_path(helper_path)
    helper_stat = helper_path.stat()

    if binary_path.exists():
        binary_stat = binary_path.stat()
        if binary_stat.st_mtime >= helper_stat.st_mtime and os.access(binary_path, os.X_OK):
            return binary_path

    command = build_compile_command(helper_path, binary_path)
    logger.info("Compiling audio capture helper: %s", command)
    subprocess.run(command, check=True)
    return binary_path


def iter_audio_stats(lines: Iterable[str]) -> Iterator[AudioStats]:
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            yield parse_audio_stats_line(line)
        except ValueError:
            logger.warning("Skipping malformed helper output: %s", line)


def parse_bite_candidate_line(line: str) -> AudioHintEvent:
    match = BITE_CANDIDATE_PATTERN.match(line.strip())
    if match is None:
        raise ValueError("Invalid bite candidate line")
    return AudioHintEvent(
        timestamp=float(match.group("timestamp")),
        rms=float(match.group("rms")),
        peak=float(match.group("peak")),
    )


def iter_bite_candidates(lines: Iterable[str]) -> Iterator[AudioHintEvent]:
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            yield parse_bite_candidate_line(line)
        except ValueError:
            logger.debug("Skipping non-candidate helper output: %s", line)


class AudioHintMonitor:
    def __init__(
        self,
        *,
        helper_path: Path | None = None,
        title_hint: str | None = None,
    ) -> None:
        self._helper_path = helper_path or default_helper_path()
        self._title_hint = title_hint or "Minecraft"
        self._events: queue.SimpleQueue[AudioHintEvent] = queue.SimpleQueue()
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None

    def start(self) -> bool:
        if self._process is not None:
            return True
        if sys.platform != "darwin":
            logger.info("Audio hint monitor disabled: supported only on macOS.")
            return False

        binary = ensure_compiled_helper(self._helper_path)
        command = build_capture_command(binary, self._title_hint)
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump_events, daemon=True)
        self._reader.start()
        return True

    def _pump_events(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for event in iter_bite_candidates(process.stdout):
            self._events.put(event)

    def poll(self) -> list[AudioHintEvent]:
        events: list[AudioHintEvent] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
        stderr_output = ""
        if process.stderr is not None:
            stderr_output = process.stderr.read().strip()
        if stderr_output:
            logger.info("Audio helper stderr:\n%s", stderr_output)
        process.wait(timeout=5)
        self._process = None
        self._reader = None


def run_probe(
    *,
    helper_path: Path | None = None,
    title_hint: str | None = None,
    detector: AudioSplashDetector | None = None,
    output: TextIO | None = None,
) -> int:
    if sys.platform != "darwin":
        raise SystemExit("Audio probe currently supports macOS only.")

    helper = helper_path or default_helper_path()
    sink = output or sys.stdout
    detector = detector or AudioSplashDetector()
    binary = ensure_compiled_helper(helper)

    command = build_capture_command(binary, title_hint)
    logger.info("Launching audio capture helper: %s", command)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert process.stdout is not None
    assert process.stderr is not None

    try:
        for stats in iter_audio_stats(process.stdout):
            if detector.observe(stats):
                message = (
                    f"BITE_CANDIDATE t={stats.timestamp:.3f} "
                    f"rms={stats.rms:.4f} peak={stats.peak:.4f}"
                )
                print(
                    message,
                    file=sink,
                    flush=True,
                )
    finally:
        if process.poll() is None:
            process.terminate()
        stderr_output = process.stderr.read().strip()
        if stderr_output:
            logger.info("Audio helper stderr:\n%s", stderr_output)
        process.wait(timeout=5)

    return process.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture Minecraft app audio on macOS and flag likely fishing splash events."
    )
    parser.add_argument("--title-hint", default="Minecraft")
    parser.add_argument("--helper-path", type=Path, default=default_helper_path())
    parser.add_argument("--print-command", action="store_true")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    command = build_capture_command(compiled_helper_path(args.helper_path), args.title_hint)
    if args.print_command:
        print(" ".join(command))
        return 0

    return run_probe(helper_path=args.helper_path, title_hint=args.title_hint)


if __name__ == "__main__":
    raise SystemExit(main())
