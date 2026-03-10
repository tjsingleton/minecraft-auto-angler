from __future__ import annotations

import argparse
import collections
import csv
import json
from pathlib import Path

STAGE_FIELDS = ("capture", "detect", "preview", "record")


def _pct(part: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return round((part / total) * 100, 1)


def summarize_profile(profile_csv: Path) -> dict[str, float | str]:
    profile_csv = Path(profile_csv)
    with profile_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        return {
            "avg_fps": 0.0,
            "avg_total_ms": 0.0,
            "avg_capture_ms": 0.0,
            "avg_detect_ms": 0.0,
            "avg_preview_ms": 0.0,
            "avg_record_ms": 0.0,
            "avg_vision_age_ms": 0.0,
            "avg_record_queue_depth": 0.0,
            "capture_pct": 0.0,
            "detect_pct": 0.0,
            "preview_pct": 0.0,
            "record_pct": 0.0,
            "max_vision_dropped_frames": 0,
            "max_record_dropped_frames": 0,
            "top_stage": "capture",
        }

    count = float(len(rows))
    avg_total_ms = sum(float(row["total_ms"]) for row in rows) / count
    averages = {
        stage: sum(float(row[f"{stage}_ms"]) for row in rows) / count for stage in STAGE_FIELDS
    }
    top_stage = max(STAGE_FIELDS, key=averages.__getitem__)

    return {
        "avg_fps": round((1000.0 / avg_total_ms), 1) if avg_total_ms > 0 else 0.0,
        "avg_total_ms": round(avg_total_ms, 1),
        "avg_capture_ms": round(averages["capture"], 1),
        "avg_detect_ms": round(averages["detect"], 1),
        "avg_preview_ms": round(averages["preview"], 1),
        "avg_record_ms": round(averages["record"], 1),
        "avg_vision_age_ms": round(_average_optional(rows, "vision_age_ms"), 1),
        "avg_record_queue_depth": round(_average_optional(rows, "record_queue_depth"), 1),
        "capture_pct": _pct(averages["capture"], avg_total_ms),
        "detect_pct": _pct(averages["detect"], avg_total_ms),
        "preview_pct": _pct(averages["preview"], avg_total_ms),
        "record_pct": _pct(averages["record"], avg_total_ms),
        "max_vision_dropped_frames": int(_max_optional(rows, "vision_dropped_frames")),
        "max_record_dropped_frames": int(_max_optional(rows, "record_dropped_frames")),
        "top_stage": top_stage,
    }


def summarize_session(profile_csv: Path) -> dict[str, object]:
    profile_csv = Path(profile_csv)
    summary: dict[str, object] = dict(summarize_profile(profile_csv))

    profile_rows = _read_csv_rows(profile_csv)
    first_profile_row = profile_rows[0] if profile_rows else {}
    summary["audioHintsEnabled"] = first_profile_row.get("audio_hints_enabled", "0") == "1"
    summary["autoStrafeEnabled"] = first_profile_row.get("auto_strafe_enabled", "0") == "1"
    summary["timingConfig"] = {
        "castSettleMinMs": _parse_int(first_profile_row.get("cast_settle_min_ms")),
        "castSettleMaxMs": _parse_int(first_profile_row.get("cast_settle_max_ms")),
        "recastMinMs": _parse_int(first_profile_row.get("recast_min_ms")),
        "recastMaxMs": _parse_int(first_profile_row.get("recast_max_ms")),
    }

    trace_csv = _infer_trace_path(profile_csv)
    if not trace_csv.exists():
        summary["eventCounts"] = {}
        summary["triggerSequence"] = []
        return summary

    trace_rows = _read_csv_rows(trace_csv)
    counter: collections.Counter[str] = collections.Counter()
    trigger_sequence: list[dict[str, object]] = []
    for row in trace_rows:
        event = row.get("event", "")
        if not event:
            continue
        counter[event] += 1
        trigger_sequence.append(
            {
                "timeS": _parse_float(row.get("time_s")),
                "event": event,
                "source": row.get("source", ""),
                "scheduledDelayMs": _parse_int(row.get("scheduled_delay_ms")),
                "strafeDirection": row.get("strafe_direction", ""),
                "strafeDurationMs": _parse_int(row.get("strafe_duration_ms")),
                "strafeOffsetSteps": _parse_int(row.get("strafe_offset_steps")),
                "mouseDxPx": _parse_int(row.get("mouse_dx_px")),
                "mouseDyPx": _parse_int(row.get("mouse_dy_px")),
                "mouseOffsetXPx": _parse_int(row.get("mouse_offset_x_px")),
                "mouseOffsetYPx": _parse_int(row.get("mouse_offset_y_px")),
            }
        )

    summary["eventCounts"] = dict(counter)
    summary["triggerSequence"] = trigger_sequence
    return summary


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _infer_trace_path(profile_csv: Path) -> Path:
    return profile_csv.with_name(profile_csv.name.replace("-profile.csv", "-trace.csv"))


def _parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _average_optional(rows: list[dict[str, str]], field: str) -> float:
    values = [float(row[field]) for row in rows if row.get(field, "") not in {"", None}]
    if not values:
        return 0.0
    return sum(values) / len(values)


def _max_optional(rows: list[dict[str, str]], field: str) -> float:
    values = [float(row[field]) for row in rows if row.get(field, "") not in {"", None}]
    if not values:
        return 0.0
    return max(values)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize an AutoAngler per-session profile CSV.",
    )
    parser.add_argument("profile_csv", help="Path to a <session>-profile.csv file")
    args = parser.parse_args(argv)

    summary = summarize_session(Path(args.profile_csv).expanduser())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
