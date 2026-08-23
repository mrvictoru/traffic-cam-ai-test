"""Time-of-day baselines that adjust congestion scores to relative conditions.

A reading is compared against what *this camera normally looks like at this
hour on this weekday*, built from persisted analysis history. This converts
absolute occupancy/speed readings into "as expected" vs "unusually bad/good"
so a road that is always busy at rush hour no longer reads blocked every day.

Baselines are loaded lazily per camera from the JSONL index (density history)
and per-record JSONs (score/speed history), then cached with an mtime check so
repeated cycles do not rescan the filesystem.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)

# Minimum samples in an hour bucket before the baseline is trusted.
MIN_BASELINE_SAMPLES = int(__import__("os").getenv("BASELINE_MIN_SAMPLES", "5"))

# Number of prior weeks of same-weekday-same-hour records considered.
BASELINE_WINDOW_WEEKS = float(__import__("os").getenv("BASELINE_WINDOW_WEEKS", "14"))

# How strongly the baseline adjusts the raw score at maximum deviation.
# A z-score of |z| >= Z_SATURATION shifts the score by up to ADJUSTMENT_SCALE.
Z_SATURATION = 3.0
ADJUSTMENT_SCALE = 20.0
# Normal bucket-to-bucket variance should not visibly move the displayed score.
# Only deviations outside this z-score deadband receive a relative adjustment.
Z_DEADBAND = 1.5

_DENSITY_ORDINAL = {"light": 0, "moderate": 1, "heavy": 2, "blocked": 3}

# Cache: data_dir -> (mtime_key, {camera_id: {bucket_key: [values]}})
_SCORE_CACHE: dict[str, tuple[tuple, dict]] = {}


def hour_bucket_key(captured_at: str) -> str:
    """Bucket key like 'tue_08' from an ISO captured_at string."""
    dt = _parse_ts(captured_at)
    if dt is None:
        return ""
    weekday = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][dt.weekday()]
    return f"{weekday}_{dt.hour:02d}"


def _parse_ts(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _load_score_history(
    analyses_root: Path,
    camera_id: str,
) -> dict[str, dict[str, list[float]]]:
    """Load per-hour-bucket series of congestion scores for one camera.

    Returns {weekday_hour_key: {"scores": [...], "timestamps": [...]}}.
    """
    cam_dir = analyses_root / camera_id
    buckets: dict[str, dict[str, list[float]]] = {}
    try:
        record_paths = sorted(
            path for path in cam_dir.glob("*.json")
        )
    except OSError:
        return buckets

    cutoff = datetime.now(timezone.utc).timestamp() - BASELINE_WINDOW_WEEKS * 7 * 86400
    for path in record_paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        details = record.get("details") or {}
        score = details.get("congestion_score")
        ts = _parse_ts(str(record.get("captured_at") or ""))
        if not isinstance(score, (int, float)) or ts is None:
            continue
        if ts.timestamp() < cutoff:
            continue
        key = hour_bucket_key(record["captured_at"])
        if not key:
            continue
        entry = buckets.setdefault(key, {"scores": [], "timestamps": []})
        entry["scores"].append(float(score))
        entry["timestamps"].append(ts.timestamp())
    return buckets


def baseline_for_bucket(
    history: dict[str, dict[str, list[float]]],
    target_captured_at: str,
) -> tuple[float, int]:
    """Return (mean_score, sample_count) for the target's weekday-hour bucket."""
    key = hour_bucket_key(target_captured_at)
    if not key:
        return (float("nan"), 0)
    entry = history.get(key) or {}
    scores = entry.get("scores") or []
    if len(scores) < MIN_BASELINE_SAMPLES:
        return (float("nan"), len(scores))
    return (statistics.fmean(scores), len(scores))


def temporal_adjustment(
    current_score: float,
    baseline_mean: float,
    baseline_stdev: float,
) -> float:
    """Signed adjustment applied to a raw score based on deviation from baseline.

    Positive when the current score exceeds the typical value for this bucket
    (worse than usual), negative when better. Linear in z, saturating so a
    wild outlier cannot swing the displayed score unboundedly.
    """
    if baseline_stdev <= 1e-9:
        # Degenerate variance means every historical record in the bucket was
        # effectively the same. In that case a meaningful gap is itself the
        # anomaly signal, so allow the full adjustment range.
        delta = current_score - baseline_mean
        return max(-ADJUSTMENT_SCALE, min(ADJUSTMENT_SCALE, delta))
    z = (current_score - baseline_mean) / baseline_stdev
    if abs(z) <= Z_DEADBAND:
        return 0.0
    magnitude = (abs(z) - Z_DEADBAND) / max(1e-9, (Z_SATURATION - Z_DEADBAND))
    clamped = max(0.0, min(1.0, magnitude))
    signed = clamped if z > 0 else -clamped
    return round(signed * ADJUSTMENT_SCALE, 2)


def adjusted_congestion_score(
    current_score: float,
    history: dict[str, dict[str, list[float]]],
    captured_at: str,
) -> tuple[float, dict]:
    """Blend a raw congestion score with its time-of-day baseline.

    Returns (adjusted_score, metadata). When the bucket lacks enough history,
    returns the raw score unchanged with `baseline_applied: False` so callers
    degrade gracefully during the first weeks of operation.
    """
    meta: dict = {"baseline_applied": False}
    mean, count = baseline_for_bucket(history, captured_at)
    if count < MIN_BASELINE_SAMPLES or mean != mean:  # NaN check
        meta["reason"] = f"insufficient_history ({count} samples)"
        return round(current_score, 2), meta

    key = hour_bucket_key(captured_at)
    scores = (history.get(key) or {}).get("scores") or []
    stdev = statistics.stdev(scores) if len(scores) > 1 else 0.0
    adjustment = temporal_adjustment(current_score, mean, stdev)
    adjusted = max(0.0, min(100.0, current_score + adjustment))

    meta.update({
        "baseline_applied": True,
        "baseline_mean": round(mean, 2),
        "baseline_stdev": round(stdev, 2),
        "baseline_samples": count,
        "adjustment": adjustment,
    })
    return round(adjusted, 2), meta


def load_camera_baseline(
    data_dir: str | Path,
    camera_id: str,
) -> dict[str, dict[str, list[float]]]:
    """Public loader with caching keyed on the camera directory's mtime state."""
    root = Path(data_dir)
    analyses_root = root / "analyses"
    cache_sig = _directory_signature(analyses_root / camera_id)
    cached = _SCORE_CACHE.get(str(root))
    if cached and cached[0] == cache_sig:
        return cached[1]
    history = _load_score_history(analyses_root, str(camera_id))
    _SCORE_CACHE[str(root)] = (cache_sig, history)
    return history


def _directory_signature(path: Path) -> tuple:
    """Cheap change signal: newest .json mtime plus file count."""
    try:
        files = list(path.glob("*.json"))
    except OSError:
        return (0, 0)
    if not files:
        return (0, 0)
    latest = max(f.stat().st_mtime_ns for f in files)
    return (latest, len(files))


def density_ordinal(density: str | None) -> int:
    """Map a density label onto its ordinal rank for index-based baselines."""
    return _DENSITY_ORDINAL.get((density or "").lower(), 0)
