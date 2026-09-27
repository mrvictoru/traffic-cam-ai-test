"""Backfill per-camera free-flow speed calibration from persisted analysis history.

Scans data/analyses/<cam_id>/*.json for records containing
`median_speed_px_per_frame`, then screens them by sample window, detector
confidence, and active-track support. The 02:00-05:00 Asia/Macau window is a
quiet-traffic proxy, not a requirement; use a different local window only when
the footage has been reviewed and vehicles are visibly moving freely.

Usage:
    python tools/calibrate_freeflow.py [--data-dir data] \
        [--config config/camera_speed_calibration.json] \
        [--min-history 10] [--offpeak-start 2 --offpeak-end 5]
        [--min-mean-confidence 0.25] [--min-eligible-tracks 2] [--dry-run]

The 95th percentile remains a camera-relative value in pixels per sampled
frame, not a physical speed. Preview reports include rejected-sample counts
and chronological-half stability diagnostics; review those before persisting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trafficcam.config import settings
from trafficcam.calibration import (
    DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
    DEFAULT_CALIBRATION_MIN_HISTORY,
    DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    calibrate,
    calibrate_with_report,
)

LOGGER = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config", default="config/camera_speed_calibration.json")
    parser.add_argument("--min-history", type=int, default=DEFAULT_CALIBRATION_MIN_HISTORY)
    parser.add_argument("--offpeak-start", "--window-start", dest="offpeak_start", type=int, default=2)
    parser.add_argument("--offpeak-end", "--window-end", dest="offpeak_end", type=int, default=5)
    parser.add_argument("--detector-model", default=settings.vision_yolo_model_name)
    parser.add_argument(
        "--min-mean-confidence",
        type=float,
        default=DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    )
    parser.add_argument(
        "--min-eligible-tracks",
        "--min-active-tracks",
        dest="min_eligible_tracks",
        type=int,
        default=DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = calibrate_with_report(
        Path(args.data_dir),
        Path(args.config),
        min_history=args.min_history,
        dry_run=args.dry_run,
        offpeak_start=args.offpeak_start,
        offpeak_end=args.offpeak_end,
        min_mean_confidence=args.min_mean_confidence,
        min_eligible_tracks=args.min_eligible_tracks,
        detector_model=args.detector_model,
    )
    print(
        json.dumps(
            {
                "data_dir": args.data_dir,
                "config": args.config,
                "dry_run": args.dry_run,
                **result,
                "camera_count": len(result["cameras"]),
            },
            ensure_ascii=False,
            indent=2 if args.pretty else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
