"""Free-flow speed calibration helpers."""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

# Percentile of quality-screened speeds used as the camera-relative free-flow
# reference. This is not a physical speed measurement.
_FREEFLOW_PCT = 95.0
# A kept sample set is not a free-flow window when its median is far below its
# upper tail. This blocks stopped or mixed traffic from being stored as the
# reference; it is not a physical speed threshold.
_MIXTURE_MEDIAN_TO_P95 = 0.35
# Dropping several fast samples and then publishing the remaining lower tail
# is not the same as removing one isolated tracker spike.
_UPPER_TAIL_DISAGREEMENT = 1.5

# Records older than this have no motion fields; they cannot be calibrated.
_SPEED_FIELD = "median_speed_px_per_frame"
_MACAU_TIMEZONE = ZoneInfo("Asia/Macau")
DEFAULT_CALIBRATION_MIN_HISTORY = 10
DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE = 0.25
DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS = 2


@dataclass(frozen=True)
class CalibrationSample:
    captured_at: datetime
    speed_px_per_frame: float
    mean_confidence: float
    eligible_tracks: int
    confidence_basis: str = "burst_mean"


def _validate_calibration_options(
    min_history: int,
    offpeak_start: int,
    offpeak_end: int,
    min_mean_confidence: float,
    min_eligible_tracks: int,
    detector_model: str,
) -> None:
    if min_history < 1:
        raise ValueError("min_history must be at least 1")
    if not 0 <= offpeak_start <= 23 or not 0 <= offpeak_end <= 23:
        raise ValueError("sample-window hours must be between 0 and 23")
    if offpeak_start == offpeak_end:
        raise ValueError("sample-window start and end hours must differ")
    if not math.isfinite(min_mean_confidence) or not 0 <= min_mean_confidence <= 1:
        raise ValueError("min_mean_confidence must be between 0 and 1")
    if min_eligible_tracks < 1:
        raise ValueError("min_eligible_tracks must be at least 1")
    if not detector_model.strip():
        raise ValueError("detector_model must not be empty")


def _sample_window_label(start: int, end: int) -> str:
    return f"{start:02d}:00-{end:02d}:00 Asia/Macau"


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
            detector_model = entry.get("detector_model")
            if detector_model:
                record["detector_model"] = str(detector_model)
            sample_count = entry.get("sample_count")
            try:
                if sample_count is not None:
                    record["sample_count"] = int(sample_count)
            except (TypeError, ValueError):
                pass
            offpeak_hours = entry.get("offpeak_hours")
            if offpeak_hours:
                record["offpeak_hours"] = str(offpeak_hours)
            sampling_window_local = entry.get("sampling_window_local")
            if sampling_window_local:
                record["sampling_window_local"] = str(sampling_window_local)
            for key in (
                "mean_sample_confidence",
                "mean_active_tracks",
                "mean_eligible_tracks",
                "split_half_p95_ratio",
            ):
                value = entry.get(key)
                if isinstance(value, (int, float)) and math.isfinite(float(value)):
                    record[key] = float(value)
        parsed[str(camera_id)] = record
    return parsed


def _scan_history(
    data_dir: Path,
    offpeak_start: int,
    offpeak_end: int,
    min_mean_confidence: float,
    min_eligible_tracks: int,
    detector_model: str,
) -> tuple[dict[str, list[CalibrationSample]], dict[str, dict[str, Any]]]:
    """Collect quality-screened speed records in the selected local-time window."""
    analyses_root = data_dir / "analyses"
    samples: dict[str, list[CalibrationSample]] = {}
    evidence: dict[str, dict[str, Any]] = {}
    if not analyses_root.is_dir():
        return samples, evidence

    for record_path in sorted(analyses_root.glob("*/*.json")):
        camera_id = record_path.parent.name
        camera_evidence = evidence.setdefault(
            camera_id,
            {
                "total_records": 0,
                "records_in_window": 0,
                "valid_speed_records": 0,
                "quality_qualified_records": 0,
                "rejected": {
                    "unreadable_record": 0,
                    "invalid_timestamp": 0,
                    "outside_sample_window": 0,
                    "missing_motion_history": 0,
                    "invalid_speed": 0,
                    "unusable_record": 0,
                    "low_confidence": 0,
                    "missing_detector_model": 0,
                    "detector_model_mismatch": 0,
                    "missing_track_support": 0,
                    "insufficient_track_support": 0,
                },
            },
        )
        camera_evidence["total_records"] += 1
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            camera_evidence["rejected"]["unreadable_record"] += 1
            continue

        if not isinstance(record, dict):
            camera_evidence["rejected"]["unreadable_record"] += 1
            continue
        details = record.get("details")
        if not isinstance(details, dict):
            details = {}
        raw_speed = details.get(_SPEED_FIELD)
        if raw_speed is None:
            camera_evidence["rejected"]["missing_motion_history"] += 1

        captured_at = _parse_captured_at(str(record.get("captured_at") or ""))
        if captured_at is None:
            camera_evidence["rejected"]["invalid_timestamp"] += 1
            continue
        hour = captured_at.hour
        in_window = (
            offpeak_start <= hour < offpeak_end
            if offpeak_start <= offpeak_end
            else hour >= offpeak_start or hour < offpeak_end
        )
        if not in_window:
            camera_evidence["rejected"]["outside_sample_window"] += 1
            continue
        camera_evidence["records_in_window"] += 1

        if raw_speed is None:
            continue
        if (
            isinstance(raw_speed, bool)
            or not isinstance(raw_speed, (int, float))
            or not math.isfinite(float(raw_speed))
            or float(raw_speed) <= 0
        ):
            camera_evidence["rejected"]["invalid_speed"] += 1
            continue
        camera_evidence["valid_speed_records"] += 1

        record_model = details.get("detector_model")
        if not isinstance(record_model, str) or not record_model.strip():
            camera_evidence["rejected"]["missing_detector_model"] += 1
            continue
        if record_model != detector_model:
            camera_evidence["rejected"]["detector_model_mismatch"] += 1
            continue

        health = record.get("health")
        if isinstance(health, dict) and health.get("usable") is False:
            camera_evidence["rejected"]["unusable_record"] += 1
            continue

        raw_confidence, confidence_basis = _screening_confidence(details)
        if (
            raw_confidence is None
            or float(raw_confidence) < min_mean_confidence
        ):
            camera_evidence["rejected"]["low_confidence"] += 1
            continue

        motion_support = details.get("motion_support")
        if (
            not isinstance(motion_support, dict)
            or motion_support.get("eligible_tracks_evaluated") is not True
        ):
            camera_evidence["rejected"]["missing_track_support"] += 1
            continue
        raw_tracks = motion_support.get("eligible_tracks")
        if (
            isinstance(raw_tracks, bool)
            or not isinstance(raw_tracks, int)
        ):
            camera_evidence["rejected"]["missing_track_support"] += 1
            continue
        if raw_tracks < min_eligible_tracks:
            camera_evidence["rejected"]["insufficient_track_support"] += 1
            continue

        camera_evidence["quality_qualified_records"] += 1
        samples.setdefault(camera_id, []).append(
            CalibrationSample(
                captured_at=captured_at,
                speed_px_per_frame=float(raw_speed),
                mean_confidence=float(raw_confidence),
                eligible_tracks=raw_tracks,
                confidence_basis=confidence_basis,
            )
        )
    return samples, evidence


def _screening_confidence(details: dict[str, Any]) -> tuple[float | None, str]:
    """Return confidence for the calibration screen.

    Burst-mean confidence includes frames with no detections as zeros. When
    per-frame results are stored, screen on frames that actually contain
    vehicles so empty frames do not hide confident motion.
    """
    frames = details.get("per_frame")
    if isinstance(frames, list) and frames:
        occupied: list[float] = []
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            count = frame.get("vehicle_count")
            confidence = frame.get("confidence")
            if isinstance(count, bool) or not isinstance(count, (int, float)) or count <= 0:
                continue
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not math.isfinite(float(confidence))
            ):
                continue
            occupied.append(float(confidence))
        if occupied:
            return sum(occupied) / len(occupied), "occupied_frames"
        return 0.0, "occupied_frames"

    raw_confidence = details.get("mean_confidence")
    if (
        isinstance(raw_confidence, bool)
        or not isinstance(raw_confidence, (int, float))
        or not math.isfinite(float(raw_confidence))
    ):
        return None, "burst_mean"
    return float(raw_confidence), "burst_mean"


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _upper_fence(sorted_values: list[float]) -> float:
    """Fence isolated high spikes without deleting a repeated faster mode.

    A median multiple treats every faster vehicle as an outlier when most
    samples are stopped. A Tukey fence keeps a repeated upper mode and still
    drops a single jump above a tight cluster.
    """
    if len(sorted_values) < 4:
        return float("inf")
    q1 = _percentile(sorted_values, 25.0)
    q3 = _percentile(sorted_values, 75.0)
    iqr = q3 - q1
    if iqr <= 1e-9:
        return max(q3 * 2.0, _percentile(sorted_values, 50.0) * 2.0, 1e-6)
    return q3 + (3.0 * iqr)


def _trimmed(values: list[float]) -> list[float]:
    """Drop isolated high spikes that would corrupt a small-sample percentile."""
    if len(values) < 3:
        return list(values)
    ordered = sorted(values)
    fence = _upper_fence(ordered)
    kept = [value for value in values if value <= fence]
    return kept or list(values)


def _value_distribution(values: list[float]) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {
            "sample_count": 0,
            "median_px_per_frame": None,
            "p95_px_per_frame": None,
        }
    return {
        "sample_count": len(ordered),
        "median_px_per_frame": round(_percentile(ordered, 50.0), 3),
        "p95_px_per_frame": round(_percentile(ordered, _FREEFLOW_PCT), 3),
    }


def _persistence_block(raw_values: list[float], trimmed_values: list[float]) -> str | None:
    """Return why a numeric candidate must not be stored as free-flow."""
    if not trimmed_values:
        return None
    raw = _value_distribution(raw_values)
    trimmed = _value_distribution(trimmed_values)
    trimmed_median = trimmed["median_px_per_frame"]
    trimmed_p95 = trimmed["p95_px_per_frame"]
    raw_p95 = raw["p95_px_per_frame"]
    removed = len(raw_values) - len(trimmed_values)
    if (
        trimmed_median is not None
        and trimmed_p95
        and trimmed_median / trimmed_p95 < _MIXTURE_MEDIAN_TO_P95
    ):
        return "stopped_dominated"
    if (
        removed >= 2
        and raw_p95
        and trimmed_p95
        and raw_p95 > trimmed_p95 * _UPPER_TAIL_DISAGREEMENT
    ):
        return "upper_tail_disagrees"
    return None


def _distribution(samples: list[CalibrationSample]) -> dict[str, Any]:
    values = sorted(_trimmed([sample.speed_px_per_frame for sample in samples]))
    if not values:
        return {
            "sample_count": 0,
            "median_px_per_frame": None,
            "p95_px_per_frame": None,
        }
    return {
        "sample_count": len(values),
        "median_px_per_frame": round(_percentile(values, 50.0), 3),
        "p95_px_per_frame": round(_percentile(values, _FREEFLOW_PCT), 3),
    }


def _camera_evidence_report(
    samples: list[CalibrationSample],
    scan_evidence: dict[str, Any],
    min_history: int,
) -> dict[str, Any]:
    ordered = sorted(samples, key=lambda sample: sample.captured_at)
    raw_values = [sample.speed_px_per_frame for sample in ordered]
    trimmed_values = _trimmed(raw_values)
    all_distribution = _distribution(ordered)
    raw_distribution = _value_distribution(raw_values)
    basis_counts: dict[str, int] = {}
    for sample in ordered:
        basis_counts[sample.confidence_basis] = basis_counts.get(sample.confidence_basis, 0) + 1
    midpoint = len(ordered) // 2
    first_half = _distribution(ordered[:midpoint])
    second_half = _distribution(ordered[midpoint:])
    first_p95 = first_half["p95_px_per_frame"]
    second_p95 = second_half["p95_px_per_frame"]
    split_ratio = (
        round(max(first_p95, second_p95) / min(first_p95, second_p95), 3)
        if first_p95 and second_p95
        else None
    )
    return {
        **scan_evidence,
        "sample_count_after_outlier_trim": all_distribution["sample_count"],
        "median_px_per_frame": all_distribution["median_px_per_frame"],
        "p95_px_per_frame": all_distribution["p95_px_per_frame"],
        "raw_sample_count": raw_distribution["sample_count"],
        "raw_median_px_per_frame": raw_distribution["median_px_per_frame"],
        "raw_p95_px_per_frame": raw_distribution["p95_px_per_frame"],
        "high_outlier_count": len(raw_values) - len(trimmed_values),
        "persistence_block": _persistence_block(raw_values, trimmed_values),
        "confidence_basis_counts": basis_counts,
        "mean_sample_confidence": (
            round(sum(sample.mean_confidence for sample in ordered) / len(ordered), 3)
            if ordered
            else None
        ),
        "mean_eligible_tracks": (
            round(sum(sample.eligible_tracks for sample in ordered) / len(ordered), 2)
            if ordered
            else None
        ),
        "chronological_halves": {
            "first": first_half,
            "second": second_half,
            "p95_ratio": split_ratio,
            "review_status": (
                "insufficient_split_history"
                if min(first_half["sample_count"], second_half["sample_count"]) < min_history
                else "review_required"
            ),
        },
    }


def calibrate_with_report(
    data_dir: Path,
    config_path: Path,
    min_history: int,
    dry_run: bool,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
    min_mean_confidence: float = DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    min_eligible_tracks: int = DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
    detector_model: str | None = None,
) -> dict[str, Any]:
    """Compute a quality report and optionally persist eligible baselines."""
    detector_model = detector_model or settings.vision_yolo_model_name
    _validate_calibration_options(
        min_history,
        offpeak_start,
        offpeak_end,
        min_mean_confidence,
        min_eligible_tracks,
        detector_model,
    )
    samples_by_camera, scan_evidence = _scan_history(
        data_dir,
        offpeak_start,
        offpeak_end,
        min_mean_confidence,
        min_eligible_tracks,
        detector_model,
    )
    calibrated: dict[str, dict[str, Any]] = {}
    camera_reports: dict[str, dict[str, Any]] = {}

    existing = load_camera_calibrations(config_path)

    for camera_id in sorted(set(scan_evidence) | set(samples_by_camera)):
        samples = samples_by_camera.get(camera_id, [])
        report = _camera_evidence_report(
            samples,
            scan_evidence.get(camera_id, {}),
            min_history,
        )
        camera_reports[camera_id] = report
        values = sorted(_trimmed([sample.speed_px_per_frame for sample in samples]))
        if len(values) < min_history:
            LOGGER.info(
                "camera %s: %d quality-qualified samples < min %d - skipping",
                camera_id,
                len(values),
                min_history,
            )
            continue
        persistence_block = report.get("persistence_block")
        if persistence_block:
            LOGGER.info(
                "camera %s: not persisting free-flow candidate (%s)",
                camera_id,
                persistence_block,
            )
            continue
        freeflow = round(_percentile(values, _FREEFLOW_PCT), 3)
        if freeflow <= 0:
            LOGGER.warning("camera %s: non-positive freeflow %.3f, skipping", camera_id, freeflow)
            continue
        calibrated[camera_id] = {
            "freeflow_px_per_frame": freeflow,
            "detector_model": detector_model,
            "sample_count": len(values),
            "sampling_window_local": _sample_window_label(offpeak_start, offpeak_end),
            "mean_sample_confidence": report["mean_sample_confidence"],
            "mean_eligible_tracks": report["mean_eligible_tracks"],
            "split_half_p95_ratio": report["chronological_halves"]["p95_ratio"],
        }
        LOGGER.info(
            "camera %s: freeflow=%.3f px/sample-frame (%d quality-qualified samples)",
            camera_id,
            freeflow,
            len(values),
        )

    result = {
        "sample_window_local": _sample_window_label(offpeak_start, offpeak_end),
        "detector_model": detector_model,
        "min_history": min_history,
        "quality_thresholds": {
            "min_mean_confidence": min_mean_confidence,
            "min_eligible_tracks": min_eligible_tracks,
            "min_active_tracks": min_eligible_tracks,
            "detector_model": detector_model,
        },
        "cameras": calibrated,
        "evidence": camera_reports,
    }

    if not calibrated:
        blocked = [
            camera_id
            for camera_id, report in camera_reports.items()
            if report.get("persistence_block")
            and int(report.get("sample_count_after_outlier_trim") or 0) >= min_history
        ]
        if blocked:
            LOGGER.warning(
                "No free-flow baselines written. %d camera(s) had enough samples but were blocked: %s",
                len(blocked),
                ", ".join(blocked),
            )
        else:
            LOGGER.warning("No cameras had enough quality-qualified motion history to calibrate.")
        return result

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

    return result


def calibrate(
    data_dir: Path,
    config_path: Path,
    min_history: int,
    dry_run: bool,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
    min_mean_confidence: float = DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    min_eligible_tracks: int = DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
    detector_model: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Backward-compatible candidate mapping wrapper for calibration callers."""
    return calibrate_with_report(
        data_dir,
        config_path,
        min_history,
        dry_run,
        offpeak_start,
        offpeak_end,
        min_mean_confidence,
        min_eligible_tracks,
        detector_model,
    )["cameras"]


def summarize_calibration_coverage(
    manifest_camera_ids: list[str],
    data_dir: Path,
    config_path: Path,
    min_history: int = DEFAULT_CALIBRATION_MIN_HISTORY,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
    min_mean_confidence: float = DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    min_eligible_tracks: int = DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
    detector_model: str | None = None,
) -> dict[str, Any]:
    """Report calibration coverage and readiness for manifest cameras."""
    detector_model = detector_model or settings.vision_yolo_model_name
    _validate_calibration_options(
        min_history,
        offpeak_start,
        offpeak_end,
        min_mean_confidence,
        min_eligible_tracks,
        detector_model,
    )
    samples_by_camera, scan_evidence = _scan_history(
        data_dir,
        offpeak_start,
        offpeak_end,
        min_mean_confidence,
        min_eligible_tracks,
        detector_model,
    )
    configured = load_camera_calibrations(config_path)

    status_by_camera: dict[str, str] = {}
    evidence_by_camera: dict[str, dict[str, Any]] = {}
    for camera_id in sorted(set(str(camera_id) for camera_id in manifest_camera_ids)):
        samples = samples_by_camera.get(camera_id, [])
        evidence = _camera_evidence_report(
            samples,
            scan_evidence.get(camera_id, {}),
            min_history,
        )
        evidence_by_camera[camera_id] = evidence
        values = sorted(_trimmed([sample.speed_px_per_frame for sample in samples]))
        persistence_block = evidence.get("persistence_block")
        if camera_id in configured:
            status = "calibrated"
        elif len(values) >= min_history and persistence_block:
            status = str(persistence_block)
        elif len(values) >= min_history:
            status = "ready"
        elif len(values) > 0:
            status = "insufficient_history"
        elif evidence.get("quality_qualified_records", 0) == 0 and evidence.get("valid_speed_records", 0) > 0:
            status = "low_quality_history"
        elif evidence.get("rejected", {}).get("missing_motion_history", 0):
            status = "missing_motion_history"
        elif evidence.get("total_records", 0) and evidence.get("records_in_window", 0) == 0:
            status = "no_offpeak_history"
        elif evidence.get("total_records", 0):
            status = "low_quality_history"
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
        "evidence_by_camera": evidence_by_camera,
        "min_history": min_history,
        "offpeak_hours": f"{offpeak_start:02d}-{offpeak_end:02d}",
        "sampling_window_local": _sample_window_label(offpeak_start, offpeak_end),
        "detector_model": detector_model,
        "quality_thresholds": {
            "min_mean_confidence": min_mean_confidence,
            "min_eligible_tracks": min_eligible_tracks,
            "min_active_tracks": min_eligible_tracks,
            "detector_model": detector_model,
        },
    }


def offpeak_window_status(
    now: datetime | None = None,
    *,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
) -> dict[str, Any]:
    """Describe the current Asia/Macau free-flow collection window."""
    current = now.astimezone(_MACAU_TIMEZONE) if now else datetime.now(_MACAU_TIMEZONE)
    start = current.replace(hour=offpeak_start, minute=0, second=0, microsecond=0)
    end = current.replace(hour=offpeak_end, minute=0, second=0, microsecond=0)
    if offpeak_start <= offpeak_end:
        in_window = start <= current < end
        if current < start:
            next_start, next_end = start, end
        elif in_window:
            next_start, next_end = start, end
        else:
            next_start, next_end = start + timedelta(days=1), end + timedelta(days=1)
    else:
        in_window = current >= start or current < end
        if current >= start:
            next_start = start
            next_end = end + timedelta(days=1)
        elif current < end:
            next_start = start - timedelta(days=1)
            next_end = end
        else:
            next_start, next_end = start, end + timedelta(days=1)
    minutes_until = 0 if in_window else max(0, int((next_start - current).total_seconds() // 60))
    return {
        "timezone": "Asia/Macau",
        "local_time": current.isoformat(),
        "offpeak_hours": f"{offpeak_start:02d}:00-{offpeak_end:02d}:00",
        "in_offpeak_window": in_window,
        "is_recommended_window": in_window,
        "can_collect_freeflow_samples": True,
        "next_window_start": next_start.isoformat(),
        "next_window_end": next_end.isoformat(),
        "minutes_until_next_window": minutes_until,
    }


def _summary_count(summary: dict[str, Any] | None, *keys: str) -> int:
    payload = summary or {}
    status_counts = payload.get("status_counts") if isinstance(payload.get("status_counts"), dict) else {}
    for key in keys:
        if key in payload and payload[key] is not None:
            try:
                return int(payload[key])
            except (TypeError, ValueError):
                continue
        if key in status_counts:
            try:
                return int(status_counts[key])
            except (TypeError, ValueError):
                continue
    return 0


def _task(
    *,
    task_id: str,
    owner: str,
    status: str,
    title: str,
    detail: str,
    action: str,
    remaining: int = 0,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "owner": owner,
        "status": status,
        "title": title,
        "detail": detail,
        "action": action,
        "remaining": remaining,
    }


def build_human_calibration(
    *,
    camera_count: int,
    missing_coordinates: int,
    missing_rois: int,
    missing_flow_lines: int,
    disabled_corridor_names: list[str] | None = None,
    enabled_corridor_count: int = 0,
    calibration_summary: dict[str, Any] | None = None,
    now: datetime | None = None,
    offpeak_start: int = 2,
    offpeak_end: int = 5,
    min_history: int = DEFAULT_CALIBRATION_MIN_HISTORY,
    min_mean_confidence: float = DEFAULT_CALIBRATION_MIN_MEAN_CONFIDENCE,
    min_eligible_tracks: int = DEFAULT_CALIBRATION_MIN_ELIGIBLE_TRACKS,
) -> dict[str, Any]:
    """Build an explicit human-vs-automated calibration checklist."""
    window = offpeak_window_status(now, offpeak_start=offpeak_start, offpeak_end=offpeak_end)
    disabled = list(disabled_corridor_names or [])
    configured = _summary_count(calibration_summary, "configured", "configured_count")
    ready = _summary_count(calibration_summary, "ready")
    uncalibrated = max(camera_count - configured, _summary_count(calibration_summary, "missing", "missing_count"))
    need_freeflow_history = max(
        0,
        camera_count
        - configured
        - ready,
    )
    human_remaining = missing_coordinates + missing_rois + missing_flow_lines + len(disabled)
    tasks = [
        _task(
            task_id="place-cameras",
            owner="human",
            status="done" if missing_coordinates == 0 else "blocked",
            title=(
                "All cameras have verified map positions"
                if missing_coordinates == 0
                else f"Place {missing_coordinates} cameras on the real road"
            ),
            detail="Approximate district jitter is not accurate enough for Google-Maps-like traffic. Only verified coordinates are shown on the map by default.",
            action="Turn on Edit positions and drag each marker onto the camera's real location, or edit config/camera_coordinates.json.",
            remaining=missing_coordinates,
        ),
        _task(
            task_id="draw-rois",
            owner="human",
            status="done" if missing_rois == 0 else "blocked",
            title=(
                "Roadway ROIs are configured"
                if missing_rois == 0
                else f"Draw roadway ROIs for {missing_rois} cameras"
            ),
            detail="Without a roadway ROI, occupancy can count sidewalks, sky, or adjacent roads.",
            action="Edit config/camera_rois.json against a live frame so the polygon covers only the travel lanes.",
            remaining=missing_rois,
        ),
        _task(
            task_id="draw-flow-lines",
            owner="human",
            status="done" if missing_flow_lines == 0 else "blocked",
            title=(
                "Flow lines are configured"
                if missing_flow_lines == 0
                else f"Draw flow lines for {missing_flow_lines} cameras"
            ),
            detail="Directional counts need a human-drawn line across the lanes of travel.",
            action="Edit config/camera_flow_lines.json so the line crosses the roadway, not the camera housing or sky.",
            remaining=missing_flow_lines,
        ),
        _task(
            task_id="verify-corridors",
            owner="human",
            status="done" if not disabled else "blocked",
            title=(
                "Named corridor geometry is verified"
                if not disabled
                else f"Verify geometry before enabling {len(disabled)} corridors"
            ),
            detail="Disabled named-road candidates stay hidden until camera order and coordinates are confirmed: "
            + (", ".join(disabled) if disabled else "none"),
            action="Confirm positions in config/camera_corridors.json, then set enabled to true.",
            remaining=len(disabled),
        ),
        _task(
            task_id="collect-offpeak-motion",
            owner="automated",
            status=(
                "done"
                if need_freeflow_history == 0
                else "ready"
            ),
            title=(
                "Quality-screened free-flow motion history is complete"
                if need_freeflow_history == 0
                else f"Collect verified free-flow motion for {need_freeflow_history} cameras"
            ),
            detail=(
                "02:00-05:00 Asia/Macau is a quiet-traffic proxy, not a requirement. "
                "Use footage reviewed as freely moving (not queued, stopped, or empty), with at least 30 frames per burst. "
                f"Calibration screens at confidence >= {min_mean_confidence:.2f} "
                "(occupied frames when per-frame results exist, otherwise the burst mean) and "
                f"{min_eligible_tracks} eligible tracks with sufficient trajectory support; "
                "these defaults are provisional. Mixed or stopped-dominated windows are not persisted."
            ),
            action=(
                "docker compose --profile capture run --no-deps live-capture run-once "
                "--frame-count 30 --manifest-file data/manifest.json --output-dir output/live --data-dir data"
            ),
            remaining=need_freeflow_history,
        ),
        _task(
            task_id="run-calibrate-freeflow",
            owner="automated",
            status="done" if uncalibrated == 0 else "ready" if ready > 0 else "waiting",
            title=(
                "Free-flow baselines are persisted"
                if uncalibrated == 0
                else (
                    f"Preview calibrate-freeflow for {ready} quality-qualified cameras"
                    if ready > 0
                    else f"Collect {min_history} quality-qualified samples per camera"
                )
            ),
            detail=(
                "Choose the Asia/Macau sampling hours to match the reviewed footage. "
                "Inspect rejected-sample counts and chronological-half p95 stability before persisting."
            ),
            action=(
                "python -m trafficcam.cli calibrate-freeflow --data-dir data "
                "--min-history 10 --dry-run"
            ),
            remaining=uncalibrated,
        ),
    ]
    return {
        "human_required": human_remaining > 0,
        "human_remaining": human_remaining,
        "offpeak_window": window,
        "gaps": {
            "camera_count": camera_count,
            "missing_coordinates": missing_coordinates,
            "missing_rois": missing_rois,
            "missing_flow_lines": missing_flow_lines,
            "enabled_corridors": enabled_corridor_count,
            "disabled_corridors": len(disabled),
            "disabled_corridor_names": disabled,
            "configured": configured,
            "ready_for_calibrate_freeflow": ready,
            "need_freeflow_history": need_freeflow_history,
            "need_offpeak_history": need_freeflow_history,
        },
        "tasks": tasks,
    }