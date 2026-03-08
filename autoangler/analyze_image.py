from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from autoangler.line_detector import FishingLineDetector, LineCandidate, centered_tracking_box


@dataclass(frozen=True)
class FrameAnalysis:
    tracking_box: tuple[int, int, int, int]
    crop: np.ndarray
    mask: np.ndarray
    overlay: np.ndarray
    line_pixels: int
    candidate: LineCandidate | None


def parse_box(value: str) -> tuple[int, int, int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4 or any(not part.lstrip("-").isdigit() for part in parts):
        raise argparse.ArgumentTypeError("box must be x1,y1,x2,y2")
    x1, y1, x2, y2 = (int(part) for part in parts)
    if x2 <= x1 or y2 <= y1:
        raise argparse.ArgumentTypeError("box must satisfy x2>x1 and y2>y1")
    return x1, y1, x2, y2


def analyze_frame(
    frame: np.ndarray,
    *,
    tracking_box: tuple[int, int, int, int] | None,
    tracking_box_size: int = 80,
    detector: FishingLineDetector | None = None,
) -> FrameAnalysis:
    detector = detector or FishingLineDetector()
    gray = _to_gray(frame)
    tracking_box = _normalized_tracking_box(
        gray.shape,
        tracking_box=tracking_box,
        tracking_box_size=tracking_box_size,
    )
    x1, y1, x2, y2 = tracking_box
    crop = gray[y1:y2, x1:x2]
    mask = detector.threshold_dark_pixels(crop)
    line_pixels = int(np.sum(mask == 0))
    candidate = detector.find_line(crop)
    overlay = _build_overlay(gray, tracking_box, candidate)
    return FrameAnalysis(
        tracking_box=tracking_box,
        crop=crop,
        mask=mask,
        overlay=overlay,
        line_pixels=line_pixels,
        candidate=candidate,
    )


def write_analysis_outputs(
    image_path: Path,
    analysis: FrameAnalysis,
    *,
    output_dir: Path | None = None,
) -> dict[str, object]:
    image_path = image_path.resolve()
    if output_dir is None:
        output_dir = image_path.parent / f"{image_path.stem}-analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    crop_path = output_dir / f"{image_path.stem}-analysis-crop.png"
    mask_path = output_dir / f"{image_path.stem}-analysis-mask.png"
    overlay_path = output_dir / f"{image_path.stem}-analysis-overlay.png"
    summary_path = output_dir / f"{image_path.stem}-analysis.json"

    cv2.imwrite(str(crop_path), analysis.crop)
    cv2.imwrite(str(mask_path), analysis.mask)
    cv2.imwrite(str(overlay_path), analysis.overlay)

    summary = {
        "image_path": str(image_path),
        "tracking_box": list(analysis.tracking_box),
        "line_pixels": analysis.line_pixels,
        "candidate_bbox": list(analysis.candidate.bbox) if analysis.candidate else None,
        "candidate_center": list(analysis.candidate.center) if analysis.candidate else None,
        "candidate_score": analysis.candidate.score if analysis.candidate else None,
        "crop_path": str(crop_path),
        "mask_path": str(mask_path),
        "overlay_path": str(overlay_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    image_path = Path(args.image_path).expanduser()
    frame = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if frame is None:
        raise SystemExit(f"Could not read image: {image_path}")

    analysis = analyze_frame(
        frame,
        tracking_box=args.box,
        tracking_box_size=args.size,
    )
    summary = write_analysis_outputs(
        image_path,
        analysis,
        output_dir=Path(args.output_dir).expanduser() if args.output_dir else None,
    )
    print(json.dumps(summary, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the current line-detection algorithm against a single image.",
    )
    parser.add_argument("image_path", help="Image to analyze")
    parser.add_argument(
        "--box",
        type=parse_box,
        help="Tracking box in x1,y1,x2,y2 image coordinates",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=80,
        help="Centered tracking-box size to use when --box is omitted",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for crop/mask/overlay/json outputs (defaults next to the image)",
    )
    return parser


def _build_overlay(
    frame: np.ndarray,
    tracking_box: tuple[int, int, int, int],
    candidate: LineCandidate | None,
) -> np.ndarray:
    overlay = frame.copy()
    x1, y1, x2, y2 = tracking_box
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color=0, thickness=1)
    if candidate is not None:
        cx1, cy1, cx2, cy2 = candidate.bbox
        cv2.rectangle(
            overlay,
            (x1 + cx1, y1 + cy1),
            (x1 + cx2, y1 + cy2),
            color=64,
            thickness=1,
        )
        cv2.circle(
            overlay,
            (x1 + candidate.center[0], y1 + candidate.center[1]),
            radius=2,
            color=64,
            thickness=-1,
        )
    return overlay


def _normalized_tracking_box(
    frame_shape: tuple[int, ...],
    *,
    tracking_box: tuple[int, int, int, int] | None,
    tracking_box_size: int,
) -> tuple[int, int, int, int]:
    if tracking_box is None:
        return centered_tracking_box(frame_shape, size=tracking_box_size)

    frame_height, frame_width = frame_shape[:2]
    x1, y1, x2, y2 = tracking_box
    left = max(0, min(x1, frame_width - 1))
    top = max(0, min(y1, frame_height - 1))
    right = max(left + 1, min(x2, frame_width))
    bottom = max(top + 1, min(y2, frame_height))
    return left, top, right, bottom


def _to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 3:
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame.copy()


if __name__ == "__main__":
    raise SystemExit(main())
