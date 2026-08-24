"""Backfill per-camera free-flow speed calibration from persisted analysis history.

Scans data/analyses/<cam_id>/*.json for records containing
`median_speed_px_per_frame`, selects observations from off-peak hours (default:
02:00-05:00 local) as the free-flow proxy, and writes the 95th-percentile of
those values into config/camera_speed_calibration.json so the speed-aware
DensityScorer can normalize each camera against its own free-flow baseline.

Usage:
    python tools/calibrate_freeflow.py [--data-dir data] \
        [--config config/camera_speed_calibration.json] \
        [--min-history 5] [--offpeak-start 2 --offpeak-end 5] [--dry-run]

Cameras whose history lacks motion data are skipped and reported, since their
records predate the speed estimator.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trafficcam.calibration import calibrate

LOGGER = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--config", default="config/camera_speed_calibration.json")
    parser.add_argument("--min-history", type=int, default=5)
    parser.add_argument("--offpeak-start", type=int, default=2)
    parser.add_argument("--offpeak-end", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    calibrate(
        Path(args.data_dir),
        Path(args.config),
        args.min_history,
        args.dry_run,
        offpeak_start=args.offpeak_start,
        offpeak_end=args.offpeak_end,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
