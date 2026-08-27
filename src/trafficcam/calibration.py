"""Free-flow speed calibration helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

# Percentile of off-peak speeds used as the free-flow reference: high enough to
# represent unobstructed motion, low enough to ignore one-off outliers.
_FREEFLOW_PCT = 95.0

# Records older than this have no motion fields; they cannot be calibrated.
_SPEED_FIELD = "median_speed_px_per_frame"
_MACAU_TIMEZONE = ZoneInfo("Asia/Macau")


def _parse_captured_at(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        captured_at = datetime.fromisoformat(value)
        if captured_at.tzinfo is None:
            return captured_at.replace(tzinfo=_MACAU_TIMEZONE)
        return captured_at.astimezone(_MACAU_TIMEZONE)
    except ValueError:
        return None


def load_camera_calibrations(
    config_path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Load per-camera calibration metadata.

    Backward compatibility: entries may be plain numeric values or structured
    objects with ``freeflow_px_per_frame`` and metadata.
    """
    target = Path(config_path or settings.camera_speed_calibration_path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    entries = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}

    parsed: dict[str, dict[str, Any]] = {}
    for camera_id, entry in entries.items():
        raw_value = entry.get("freeflow_px_per_frame") if isinstance(entry, dict) else entry
        try:
            freeflow = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if freeflow <= 0:
            continue
        record: dict[str, Any] = {"freeflow_px_per_frame": freeflow}
        if isinstance(entry, dict):
            sample_count = entry.get("sample_count")
            try:
                if sample_count is not None:
                    record["sample_count"] = int(sample_count)
            except (TypeError, ValueError):
                pass
            offpeak_hours = entry.get("offpeak_hours")
            if offpeak_hours:
                record["offpeak_hours"] = str(offpeak_hours)
        parsed[str(camera_id)] = record
    return parsed


def _scan_history(
    data_dir: Path,
    offpeak_start: int,
    offpeak_end: int,
) -> tuple[dict[str, list[float]], dict[str, int], dict[str, int]]:
    """Collect usable off-peak speeds plus per-camera record counts."""
    analyses_root = data_dir / "analyses"
    speeds: dict[str, list[float]] = {}
    skipped: dict[str, int] = {}
    total_records: dict[str, int] = {}
    if not analyses_root.is_dir():
        return speeds, skipped, total_records

    for record_path in sorted(analyses_root.glob("*/*.json")):
        camera_id = record_path.parent.name
        total_records[camera_id] = total_records.get(camera_id, 0) + 1
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
    return speeds, skipped, total_records


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _trimmed(values: list[float]) -> list[float]:
    """Drop motion outliers that would corrupt a small-sample percentile."""
    if len(values) < 3:
        return list(values)
    med = _percentile(sorted(values), 50.0)
    threshold = max(med * 2.0, 1e-6)
    kept = [value for value in values if value <= threshold]
    return kept or list(values)


def calibrate(
    data_dir: Path,
    config_path: Path,
    min_history: int,
    dry_run: bool,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
) -> dict[str, dict[str, float | int | str]]:
    """Compute and, unless dry_run, persist free-flow calibration."""
    speeds, skipped, _ = _scan_history(data_dir, offpeak_start, offpeak_end)
    calibrated: dict[str, dict[str, float | int | str]] = {}

    existing = load_camera_calibrations(config_path)

    for camera_id in sorted(set(speeds) | set(skipped)):
        values = sorted(_trimmed(speeds.get(camera_id, [])))
        if len(values) < min_history:
            LOGGER.info(
                "camera %s: %d off-peak samples < min %d%s - skipping",
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
            camera_id,
            freeflow,
            len(values),
        )

    if not calibrated:
        LOGGER.warning("No cameras had enough off-peak motion history to calibrate.")
        return calibrated

    merged = {str(camera_id): value for camera_id, value in existing.items()}
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


def summarize_calibration_coverage(
    manifest_camera_ids: list[str],
    data_dir: Path,
    config_path: Path,
    min_history: int,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
) -> dict[str, Any]:
    """Report calibration coverage and readiness for manifest cameras."""
    speeds, skipped, total_records = _scan_history(data_dir, offpeak_start, offpeak_end)
    configured = load_camera_calibrations(config_path)

    status_by_camera: dict[str, str] = {}
    for camera_id in sorted(set(str(camera_id) for camera_id in manifest_camera_ids)):
        values = sorted(_trimmed(speeds.get(camera_id, [])))
        if camera_id in configured:
            status = "calibrated"
        elif len(values) >= min_history:
            status = "ready"
        elif len(values) > 0:
            status = "insufficient_history"
        elif skipped.get(camera_id):
            status = "missing_motion_history"
        elif total_records.get(camera_id):
            status = "no_offpeak_history"
        else:
            status = "no_history"
        status_by_camera[camera_id] = status

    status_camera_ids: dict[str, list[str]] = {}
    for camera_id, status in status_by_camera.items():
        status_camera_ids.setdefault(status, []).append(camera_id)
    for camera_ids in status_camera_ids.values():
        camera_ids.sort()

    return {
        "config_file": str(config_path),
        "configured_count": len(status_camera_ids.get("calibrated", [])),
        "configured_camera_ids": status_camera_ids.get("calibrated", []),
        "missing_count": len([camera_id for camera_id, status in status_by_camera.items() if status != "calibrated"]),
        "missing_camera_ids": sorted(
            [camera_id for camera_id, status in status_by_camera.items() if status != "calibrated"]
        ),
        "status_counts": {status: len(camera_ids) for status, camera_ids in sorted(status_camera_ids.items())},
        "status_camera_ids": status_camera_ids,
        "min_history": min_history,
        "offpeak_hours": f"{offpeak_start:02d}-{offpeak_end:02d}",
    }