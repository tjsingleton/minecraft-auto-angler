from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from autoangler.line_detector import absolute_dark_mask, local_contrast_mask
from autoangler.line_watcher import LineWatcher
from autoangler.profile_session import summarize_profile

EXPERIMENT_CONTEXT = {
    "@vocab": "https://autoangler.local/experiment#",
    "sessionLog": {"@type": "@id"},
    "sessionTrace": {"@type": "@id"},
    "experimentLog": {"@type": "@id"},
    "sessionProfile": {"@type": "@id"},
}

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
RECORDING_PATTERN = re.compile(r"Saved screenshot to (?P<path>.+recording-(?P<index>\d+)\.png)$")
LOG_PREFIX_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<level>[A-Z]+) (?P<logger>[^:]+): (?P<message>.*)$"
)
WINDOW_TITLE_PATTERN = re.compile(r"Using Minecraft window '(?P<title>.+?)' at WindowInfo")


@dataclass(frozen=True)
class RecordingFrame:
    index: int
    path: Path
    wall_time: datetime


@dataclass(frozen=True)
class ManualMark:
    index: int
    wall_time: datetime
    nearest_frame_index: int | None


@dataclass(frozen=True)
class FrameScore:
    index: int
    path: Path
    line_pixels: int
    detected: bool


@dataclass(frozen=True)
class SessionLogData:
    recording_frames: list[RecordingFrame]
    manual_marks: list[ManualMark]
    cast_frame_indices: list[int]
    reel_frame_indices: list[int]


def parse_box(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4 or any(not part.lstrip("-").isdigit() for part in parts):
        raise argparse.ArgumentTypeError("box must be x1,y1,x2,y2")
    x1, y1, x2, y2 = (int(part) for part in parts)
    if x2 <= x1 or y2 <= y1:
        raise argparse.ArgumentTypeError("box must satisfy x2>x1 and y2>y1")
    return x1, y1, x2, y2


def default_experiment_log_path() -> Path:
    return Path.home() / ".autoangler" / "experiment-log.jsonld"


def parse_session_log(log_path: Path) -> SessionLogData:
    records: list[RecordingFrame] = []
    mark_times: list[datetime] = []
    cast_times: list[datetime] = []
    reel_times: list[datetime] = []

    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        match = LOG_PREFIX_PATTERN.match(raw_line)
        if match is None:
            continue

        wall_time = datetime.strptime(match.group("timestamp"), TIMESTAMP_FORMAT).replace(
            tzinfo=timezone.utc
        )
        message = match.group("message")

        recording_match = RECORDING_PATTERN.search(message)
        if recording_match is not None:
            path = Path(recording_match.group("path"))
            records.append(
                RecordingFrame(
                    index=int(recording_match.group("index")),
                    path=path,
                    wall_time=wall_time,
                )
            )
            continue

        if message == "Manual bite mark":
            mark_times.append(wall_time)
        elif message == "Cast":
            cast_times.append(wall_time)
        elif message == "Reel":
            reel_times.append(wall_time)

    records = sorted(records, key=lambda record: record.index)
    event_window_seconds = _event_window_seconds(records)
    marks = [
        ManualMark(
            index=index,
            wall_time=mark_time,
            nearest_frame_index=_nearest_frame_index(records, mark_time),
        )
        for index, mark_time in enumerate(mark_times)
        if _is_within_recording_window(records, mark_time, max_delta_seconds=event_window_seconds)
    ]
    marks = [mark for mark in marks if mark.nearest_frame_index is not None]

    return SessionLogData(
        recording_frames=records,
        manual_marks=marks,
        cast_frame_indices=_map_event_times_to_frame_indices(
            records,
            [
                event_time
                for event_time in cast_times
                if _is_within_recording_window(
                    records,
                    event_time,
                    max_delta_seconds=event_window_seconds,
                )
            ],
        ),
        reel_frame_indices=_map_event_times_to_frame_indices(
            records,
            [
                event_time
                for event_time in reel_times
                if _is_within_recording_window(
                    records,
                    event_time,
                    max_delta_seconds=event_window_seconds,
                )
            ],
        ),
    )


def run_experiment(
    *,
    session_log: Path,
    tracking_box: tuple[int, int, int, int],
    strategy: str,
    threshold: int,
    experiment_log: Path | None = None,
    session_trace: Path | None = None,
    pre_frames: int = 1,
    post_frames: int = 4,
) -> dict[str, object]:
    session_log = session_log.resolve()
    parsed = parse_session_log(session_log)
    if not parsed.recording_frames:
        raise ValueError(f"No recording frames found in {session_log}")

    frame_scores = _score_frames(
        parsed.recording_frames,
        tracking_box=tracking_box,
        strategy=strategy,
        threshold=threshold,
        reset_indices=sorted(set(parsed.cast_frame_indices + parsed.reel_frame_indices)),
    )
    detection_indices = [frame.index for frame in frame_scores if frame.detected]
    mark_results, false_positive_count = _evaluate_marks(
        parsed.manual_marks,
        detection_indices,
        pre_frames=pre_frames,
        post_frames=post_frames,
        frame_scores=frame_scores,
    )

    result: dict[str, object] = {
        "@context": EXPERIMENT_CONTEXT,
        "@type": "ExperimentRun",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sessionLog": session_log.as_uri(),
        "sessionTrace": session_trace.resolve().as_uri() if session_trace is not None else None,
        "trackingBox": list(tracking_box),
        "strategy": strategy,
        "parameters": {"threshold": threshold, "preFrames": pre_frames, "postFrames": post_frames},
        "frameCount": len(frame_scores),
        "markCount": len(mark_results),
        "detectionCount": len(detection_indices),
        "hitCount": sum(1 for mark in mark_results if mark["matchedDetectionIndex"] is not None),
        "missCount": sum(1 for mark in mark_results if mark["matchedDetectionIndex"] is None),
        "falsePositiveCount": false_positive_count,
        "markResults": mark_results,
        "detectionIndices": detection_indices,
        "linePixels": [frame.line_pixels for frame in frame_scores],
    }

    log_path = experiment_log or default_experiment_log_path()
    append_experiment_log(log_path, result)
    result["experimentLog"] = log_path.resolve().as_uri()
    return result


def append_experiment_log(log_path: Path, entry: dict[str, object]) -> Path:
    log_path = log_path.expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")
    return log_path


def run_capture_benchmark(
    *,
    session_log: Path,
    session_profile: Path,
    backend_name: str,
    session_trace: Path | None = None,
    experiment_log: Path | None = None,
) -> dict[str, object]:
    session_log = session_log.resolve()
    session_profile = session_profile.resolve()
    profile_summary = summarize_profile(session_profile)
    window_title = parse_window_title(session_log)

    result: dict[str, object] = {
        "@context": EXPERIMENT_CONTEXT,
        "@type": "CaptureBackendRun",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "backend": backend_name,
        "sessionLog": session_log.as_uri(),
        "sessionProfile": session_profile.as_uri(),
        "sessionTrace": session_trace.resolve().as_uri() if session_trace is not None else None,
        "windowTitle": window_title,
        "avgFps": profile_summary["avg_fps"],
        "avgTotalMs": profile_summary["avg_total_ms"],
        "avgCaptureMs": profile_summary["avg_capture_ms"],
        "avgDetectMs": profile_summary["avg_detect_ms"],
        "avgPreviewMs": profile_summary["avg_preview_ms"],
        "avgRecordMs": profile_summary["avg_record_ms"],
        "capturePct": profile_summary["capture_pct"],
        "detectPct": profile_summary["detect_pct"],
        "previewPct": profile_summary["preview_pct"],
        "recordPct": profile_summary["record_pct"],
        "topStage": profile_summary["top_stage"],
        "profileSummary": profile_summary,
    }

    log_path = experiment_log or default_experiment_log_path()
    append_experiment_log(log_path, result)
    result["experimentLog"] = log_path.resolve().as_uri()
    return result


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.profile:
        result = run_capture_benchmark(
            session_log=Path(args.session_log).expanduser(),
            session_profile=Path(args.profile).expanduser(),
            backend_name=args.backend,
            session_trace=Path(args.trace).expanduser() if args.trace else None,
            experiment_log=Path(args.experiment_log).expanduser() if args.experiment_log else None,
        )
        print(json.dumps(result, indent=2))
        return 0

    if args.box is None:
        raise SystemExit("--box is required unless --profile is provided")

    threshold = args.threshold
    if threshold is None:
        threshold = 12 if args.strategy == "local-contrast" else 32
    result = run_experiment(
        session_log=Path(args.session_log).expanduser(),
        session_trace=Path(args.trace).expanduser() if args.trace else None,
        tracking_box=args.box,
        strategy=args.strategy,
        threshold=threshold,
        experiment_log=Path(args.experiment_log).expanduser() if args.experiment_log else None,
        pre_frames=args.pre_frames,
        post_frames=args.post_frames,
    )
    print(json.dumps(result, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a recorded AutoAngler session and log experiment results.",
    )
    parser.add_argument("session_log", help="Path to the AutoAngler session log")
    parser.add_argument("--trace", help="Optional path to the matching session trace CSV")
    parser.add_argument("--box", type=parse_box, help="Tracking box x1,y1,x2,y2")
    parser.add_argument("--profile", help="Path to a matching <session>-profile.csv")
    parser.add_argument(
        "--backend",
        choices=("mss", "pil"),
        default="mss",
        help="Capture backend name for benchmark logging",
    )
    parser.add_argument(
        "--strategy",
        choices=("local-contrast", "absolute"),
        default="local-contrast",
        help="Scoring strategy to evaluate",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        help="Threshold for the chosen strategy (default: 12 local-contrast, 32 absolute)",
    )
    parser.add_argument("--pre-frames", type=int, default=1)
    parser.add_argument("--post-frames", type=int, default=4)
    parser.add_argument("--experiment-log", help="Append-only JSON-LD log path")
    return parser


def parse_window_title(log_path: Path) -> str | None:
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        match = LOG_PREFIX_PATTERN.match(raw_line)
        if match is None:
            continue
        title_match = WINDOW_TITLE_PATTERN.search(match.group("message"))
        if title_match is not None:
            return title_match.group("title")
    return None


def _score_frames(
    records: list[RecordingFrame],
    *,
    tracking_box: tuple[int, int, int, int],
    strategy: str,
    threshold: int,
    reset_indices: list[int],
) -> list[FrameScore]:
    watcher = LineWatcher()
    reset_indices = sorted(set(reset_indices))
    reset_set = set(reset_indices)
    scores: list[FrameScore] = []

    for record in records:
        if record.index in reset_set:
            watcher.reset()

        frame = cv2.imread(str(record.path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            raise ValueError(f"Could not read frame {record.path}")
        x1, y1, x2, y2 = _normalized_tracking_box(frame.shape, tracking_box)
        crop = frame[y1:y2, x1:x2]
        mask = _mask_for_strategy(crop, strategy=strategy, threshold=threshold)
        line_pixels = int(np.sum(mask == 0))
        detected = watcher.observe(line_pixels, active=True)
        scores.append(
            FrameScore(
                index=record.index,
                path=record.path,
                line_pixels=line_pixels,
                detected=detected,
            )
        )
        if detected:
            watcher.reset()

    return scores


def _evaluate_marks(
    manual_marks: list[ManualMark],
    detection_indices: list[int],
    *,
    pre_frames: int,
    post_frames: int,
    frame_scores: list[FrameScore],
) -> tuple[list[dict[str, object]], int]:
    unmatched_detections = detection_indices.copy()
    score_by_index = {score.index: score for score in frame_scores}
    mark_results: list[dict[str, object]] = []

    for mark in manual_marks:
        nearest_index = mark.nearest_frame_index
        if nearest_index is None:
            continue

        window_start = nearest_index - pre_frames
        window_end = nearest_index + post_frames
        matched = next(
            (
                index
                for index in unmatched_detections
                if window_start <= index <= window_end
            ),
            None,
        )
        if matched is not None:
            unmatched_detections.remove(matched)

        score = score_by_index.get(nearest_index)
        mark_results.append(
            {
                "markIndex": mark.index,
                "wallTime": mark.wall_time.isoformat(),
                "nearestFrameIndex": nearest_index,
                "nearestFrame": score.path.resolve().as_uri() if score else None,
                "linePixels": score.line_pixels if score else None,
                "matchedDetectionIndex": matched,
            }
        )

    return mark_results, len(unmatched_detections)


def _mask_for_strategy(frame: np.ndarray, *, strategy: str, threshold: int) -> np.ndarray:
    if strategy == "local-contrast":
        return local_contrast_mask(frame, contrast_threshold=threshold)
    if strategy == "absolute":
        return absolute_dark_mask(frame, black_threshold=threshold)
    raise ValueError(f"Unsupported strategy: {strategy}")


def _map_event_times_to_frame_indices(
    records: list[RecordingFrame], event_times: list[datetime]
) -> list[int]:
    return [
        nearest
        for event_time in event_times
        if (nearest := _nearest_frame_index(records, event_time)) is not None
    ]


def _nearest_frame_index(records: list[RecordingFrame], event_time: datetime) -> int | None:
    if not records:
        return None
    return min(
        records,
        key=lambda record: abs((record.wall_time - event_time).total_seconds()),
    ).index


def _event_window_seconds(records: list[RecordingFrame]) -> float:
    if len(records) < 2:
        return 2.0

    gaps = [
        abs((right.wall_time - left.wall_time).total_seconds())
        for left, right in zip(records, records[1:], strict=False)
    ]
    return max(2.0, max(gaps) * 2.0)


def _is_within_recording_window(
    records: list[RecordingFrame], event_time: datetime, *, max_delta_seconds: float
) -> bool:
    if not records:
        return False
    first = records[0].wall_time
    last = records[-1].wall_time
    return (
        first.timestamp() - max_delta_seconds
        <= event_time.timestamp()
        <= last.timestamp() + max_delta_seconds
    )


def _normalized_tracking_box(
    frame_shape: tuple[int, ...], tracking_box: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = tracking_box
    left = max(0, min(x1, frame_width - 1))
    top = max(0, min(y1, frame_height - 1))
    right = max(left + 1, min(x2, frame_width))
    bottom = max(top + 1, min(y2, frame_height))
    return left, top, right, bottom


if __name__ == "__main__":
    raise SystemExit(main())
