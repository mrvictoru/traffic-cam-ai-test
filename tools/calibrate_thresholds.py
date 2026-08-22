"""Auto-calibrate per-camera density thresholds from persisted analysis history.

Scans data/analyses/<cam_id>/*.json, computes the distribution of per-frame
vehicle counts (or congestion scores) observed historically, and writes
percentile-based light/moderate/heavy thresholds into
config/camera_density_thresholds.json so each camera's buckets reflect its
typical scene rather than global guesses.

Usage:
    python tools/calibrate_thresholds.py [--data-dir data] \
        [--config config/camera_density_thresholds.json] \
        [--min-history 10] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

LOGGER = logging.getLogger(__name__)

# Percentile cut-points for the three bucket boundaries.
_LIGHT_PCT = 50.0   # median day is "light"
_MODERATE_PCT = 80.0
_HEAVY_PCT = 95.0


def _load_counts(data_dir: Path) -> dict[str, list[int]]:
    """Collect per-frame vehicle counts grouped by camera id."""
    analyses_root = data_dir / "analyses"
    counts: dict[str, list[int]] = {}
    if not analyses_root.is_dir():
        return counts
    for record_path in sorted(analyses_root.glob("*/*.json")):
        camera_id = record_path.parent.name
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        details = record.get("details") or {}
        per_frame = details.get("per_frame") or []
        if per_frame:
            values = [int(f.get("vehicle_count") or 0) for f in per_frame]
        else:
            values = [int(details.get("vehicle_count") or 0)]
        counts.setdefault(camera_id, []).extend(values)
    return counts


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def calibrate(
    data_dir: Path,
    config_path: Path,
    min_history: int,
    dry_run: bool,
) -> dict[str, dict[str, int]]:
    """Compute and (unless dry_run) persist calibrated thresholds."""
    counts = _load_counts(data_dir)
    calibrated: dict[str, dict[str, int]] = {}

    existing: dict[str, object] = {}
    if config_path.exists():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            existing = payload.get("cameras", payload) if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            existing = {}

    for camera_id, values in sorted(counts.items()):
        if len(values) < min_history:
            LOGGER.info(
                "camera %s: %d samples < min %d, skipping",
                camera_id, len(values), min_history,
            )
            continue
        ordered = sorted(float(v) for v in values)
        # Round up to keep boundaries on integer counts; guarantee strict increase.
        light = max(1, int(_percentile(ordered, _LIGHT_PCT)) )
        moderate = max(light + 2, int(_percentile(ordered, _MODERATE_PCT)))
        heavy = max(moderate + 2, int(_percentile(ordered, _HEAVY_PCT)))
        calibrated[camera_id] = {"light": light, "moderate": moderate, "heavy": heavy}
        LOGGER.info("camera %s: light=%d moderate=%d heavy=%d", camera_id, light, moderate, heavy)

    if not calibrated:
        LOGGER.warning("No cameras had enough history to calibrate.")
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
    parser.add_argument("--config", default="config/camera_density_thresholds.json")
    parser.add_argument("--min-history", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    calibrate(Path(args.data_dir), Path(args.config), args.min_history, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
