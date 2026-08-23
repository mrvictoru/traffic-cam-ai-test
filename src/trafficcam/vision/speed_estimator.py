"""Vehicle motion speed estimation from tracker trajectories.

Converts tracked centroid histories into per-track displacement rates and
burst-level motion statistics that feed the speed-aware congestion score.

All speeds are expressed in **pixels per frame** on the source image. Real-world
units are intentionally avoided at this layer: the congestion scorer compares
the current median speed against a per-camera free-flow reference measured in
the same unit, so no metric calibration is required for a usable signal.
"""

from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

from trafficcam.config import settings

# Track histories are lists of (track_id, frame_idx, (cx, cy)) tuples.
TrackHistory = list[tuple[int, int, tuple[float, float]]]

# Minimum net displacement (px) for a track to count as "moving". Below this
# the track is considered stationary (parked, queued, or detection jitter).
STATIONARY_SPEED_PX_PER_FRAME = float(os.getenv("SPEED_STATIONARY_PX", "1.0"))

# Free-flow calibration file mapping camera_id -> free-flow px-per-frame.
SPEED_CALIBRATION_PATH = os.getenv(
    "CAMERA_SPEED_CALIBRATION_PATH",
    str(Path("config") / "camera_speed_calibration.json"),
)

_CALIBRATION_CACHE: dict[str, float] | None = None
_CALIBRATION_CACHE_KEY: tuple[str, int] | None = None


def estimate_track_speeds(
    track_histories: list[TrackHistory],
) -> list[float]:
    """Return per-track net displacement in px/frame.

    Uses net displacement (last point minus first point) divided by the frame
    span rather than the sum of per-step movements, so lateral jitter around a
    counting line does not inflate the estimate. Tracks with fewer than two
    points, or a zero-length frame span, are skipped.
    """
    speeds: list[float] = []
    for history in track_histories or []:
        if len(history) < 2:
            continue
        _, first_idx, first_pt = history[0]
        _, last_idx, last_pt = history[-1]
        span = last_idx - first_idx
        if span <= 0:
            continue
        dx = last_pt[0] - first_pt[0]
        dy = last_pt[1] - first_pt[1]
        speeds.append(((dx * dx + dy * dy) ** 0.5) / span)
    return speeds


def median_track_speed(track_histories: list[TrackHistory]) -> float | None:
    """Median px/frame displacement across all tracks with enough motion data."""
    speeds = estimate_track_speeds(track_histories)
    if not speeds:
        return None
    return statistics.median(speeds)


def moving_vehicle_count(track_histories: list[TrackHistory]) -> int:
    """Number of tracks whose net displacement exceeds the stationary threshold."""
    speeds = estimate_track_speeds(track_histories)
    return sum(1 for s in speeds if s > STATIONARY_SPEED_PX_PER_FRAME)


def speed_score_from_ratio(speed_ratio: float | None) -> float | None:
    """Map current-speed / free-flow-speed onto a 0-100 congestion component.

    A ratio of 1.0 (traffic at free flow) maps to 0; a ratio at or below
    ``SPEED_STALL_RATIO`` (near-stationary) saturates at 100. Linear in between.
    """
    if speed_ratio is None:
        return None
    stall = settings.speed_stall_ratio
    if stall >= 1.0:
        stall = 0.99
    clamped = max(stall, min(1.0, float(speed_ratio)))
    return round(max(0.0, min(1.0, (1.0 - clamped) / (1.0 - stall))) * 100.0, 2)


def _load_freeflow_calibration(path: str | Path | None = None) -> dict[str, float]:
    """Load per-camera free-flow px/frame values from the calibration file."""
    global _CALIBRATION_CACHE, _CALIBRATION_CACHE_KEY

    target = Path(path or SPEED_CALIBRATION_PATH)
    try:
        stat = target.stat()
    except OSError:
        _CALIBRATION_CACHE = {}
        _CALIBRATION_CACHE_KEY = None
        return {}

    cache_key = (str(target.resolve()), stat.st_mtime_ns)
    if _CALIBRATION_CACHE is not None and _CALIBRATION_CACHE_KEY == cache_key:
        return _CALIBRATION_CACHE

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _CALIBRATION_CACHE = {}
        _CALIBRATION_CACHE_KEY = cache_key
        return {}

    entries = payload.get("cameras") if isinstance(payload, dict) else None
    parsed: dict[str, float] = {}
    if isinstance(entries, dict):
        for camera_id, entry in entries.items():
            value = entry.get("freeflow_px_per_frame") if isinstance(entry, dict) else entry
            try:
                value = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if value > 0:
                parsed[str(camera_id)] = value

    _CALIBRATION_CACHE = parsed
    _CALIBRATION_CACHE_KEY = cache_key
    return parsed


def freeflow_for_camera(camera_id: str | None, path: str | Path | None = None) -> float | None:
    """Return the calibrated free-flow px/frame for a camera, if configured."""
    if not camera_id:
        return None
    return _load_freeflow_calibration(path).get(str(camera_id))
