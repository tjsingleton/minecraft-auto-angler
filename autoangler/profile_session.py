from __future__ import annotations

import argparse
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
            "capture_pct": 0.0,
            "detect_pct": 0.0,
            "preview_pct": 0.0,
            "record_pct": 0.0,
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
        "capture_pct": _pct(averages["capture"], avg_total_ms),
        "detect_pct": _pct(averages["detect"], avg_total_ms),
        "preview_pct": _pct(averages["preview"], avg_total_ms),
        "record_pct": _pct(averages["record"], avg_total_ms),
        "top_stage": top_stage,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize an AutoAngler per-session profile CSV.",
    )
    parser.add_argument("profile_csv", help="Path to a <session>-profile.csv file")
    args = parser.parse_args(argv)

    summary = summarize_profile(Path(args.profile_csv).expanduser())
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
