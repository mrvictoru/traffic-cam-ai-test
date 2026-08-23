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
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

LOGGER = logging.getLogger(__name__)

# Percentile of off-peak speeds used as the free-flow reference: high enough to
# represent unobstructed motion, low enough to ignore one-off outliers.
_FREEFLOW_PCT = 95.0

# Records older than this have no motion fields; they cannot be calibrated.
_SPEED_FIELD = "median_speed_px_per_frame"


def _parse_captured_at(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_offpeak_speeds(
    data_dir: Path,
    offpeak_start: int,
    offpeak_end: int,
) -> tuple[dict[str, list[float]], dict[str, int]]:
    """Collect off-peak median speeds grouped by camera id.

    Returns (speeds_by_camera, skipped_counts) where skipped_counts reports how
    many records per camera lacked usable motion data.
    """
    analyses_root = data_dir / "analyses"
    speeds: dict[str, list[float]] = {}
    skipped: dict[str, int] = {}
    if not analyses_root.is_dir():
        return speeds, skipped

    for record_path in sorted(analyses_root.glob("*/*.json")):
        camera_id = record_path.parent.name
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        details = record.get("details") or {}
        raw_speed = details.get(_SPEED_FIELD)
        if not isinstance(raw_speed, (int, float)) or float(raw_speed) <= 0:
            skipped[camera_id] = skipped.get(camera_id, 0) + 1
            continue
        captured_at = _parse_captured_at(str(record.get("captured_at") or ""))
        hour = captured_at.hour if captured_at else None
        # Off-peak window wraps midnight when start > end (e.g. 22..6).
        in_window = (
            hour is not None
            and (
                offpeak_start <= hour < offpeak_end
                if offpeak_start <= offpeak_end
                else hour >= offpeak_start or hour < offpeak_end
            )
        )
        if not in_window:
            continue
        speeds.setdefault(camera_id, []).append(float(raw_speed))
    return speeds, skipped


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _trimmed(values: list[float]) -> list[float]:
    """Drop motion outliers that would corrupt a small-sample percentile.

    Free-flow observations should cluster tightly; isolated spikes (tracker
    ID switches, detection jumps) are removed when they exceed twice the
    sample median. With tight clusters nothing is trimmed.
    """
    if len(values) < 3:
        return list(values)
    med = _percentile(sorted(values), 50.0)
    threshold = max(med * 2.0, 1e-6)
    kept = [v for v in values if v <= threshold]
    return kept or list(values)


def calibrate(
    data_dir: Path,
    config_path: Path,
    min_history: int,
    dry_run: bool,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
) -> dict[str, dict[str, float]]:
    """Compute and (unless dry_run) persist free-flow calibration."""
    speeds, skipped = _load_offpeak_speeds(data_dir, offpeak_start, offpeak_end)
    calibrated: dict[str, dict[str, float]] = {}

    existing: dict[str, object] = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            existing = payload.get("cameras", payload) if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            existing = {}

    for camera_id in sorted(set(speeds) | set(skipped)):
        values = sorted(_trimmed(speeds.get(camera_id, [])))
        if len(values) < min_history:
            LOGGER.info(
                "camera %s: %d off-peak samples < min %d%s — skipping",
                camera_id,
                len(values),
                min_history,
                f" ({skipped[camera_id]} records without motion data)" if skipped.get(camera_id) else "",
            )
            continue
        freeflow = round(_percentile(values, _FREEFLOW_PCT), 3)
        if freeflow <= 0:
            LOGGER.warning("camera %s: non-positive freeflow %.3f, skipping", camera_id, freeflow)
            continue
        calibrated[camera_id] = {
            "freeflow_px_per_frame": freeflow,
            "sample_count": len(values),
            "offpeak_hours": f"{offpeak_start:02d}-{offpeak_end:02d}",
        }
        LOGGER.info(
            "camera %s: freeflow=%.3f px/frame (%d samples)",
            camera_id, freeflow, len(values),
        )

    if not calibrated:
        LOGGER.warning("No cameras had enough off-peak motion history to calibrate.")
        return calibrated

    merged = {str(k): v for k, v in existing.items()}
    merged.update(calibrated)

    if not dry_run:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"cameras": merged}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        LOGGER.info("Wrote %s (%d cameras)", config_path, len(merged))
    else:
        LOGGER.info("Dry run: no changes written.")

    return calibrated


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
