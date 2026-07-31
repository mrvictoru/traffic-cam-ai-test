"""Convert vehicle detection counts into traffic density buckets."""

from __future__ import annotations

import json
from pathlib import Path

from trafficcam.config import settings


_THRESHOLD_CACHE: dict[str, tuple[int, int, int]] | None = None
_THRESHOLD_CACHE_KEY: tuple[str, int] | None = None


def _parse_threshold_entry(entry: object) -> tuple[int, int, int] | None:
    if not isinstance(entry, dict):
        return None
    try:
        light = int(entry.get("light"))
        moderate = int(entry.get("moderate"))
        heavy = int(entry.get("heavy"))
    except (TypeError, ValueError):
        return None
    if not (0 <= light < moderate < heavy):
        return None
    return (light, moderate, heavy)


def _load_camera_thresholds() -> dict[str, tuple[int, int, int]]:
    global _THRESHOLD_CACHE
    global _THRESHOLD_CACHE_KEY

    config_path = Path(settings.camera_density_thresholds_path)
    try:
        stat = config_path.stat()
    except OSError:
        _THRESHOLD_CACHE = {}
        _THRESHOLD_CACHE_KEY = None
        return {}

    cache_key = (str(config_path.resolve()), stat.st_mtime_ns)
    if _THRESHOLD_CACHE is not None and _THRESHOLD_CACHE_KEY == cache_key:
        return _THRESHOLD_CACHE

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _THRESHOLD_CACHE = {}
        _THRESHOLD_CACHE_KEY = cache_key
        return {}

    entries: dict[str, object]
    if isinstance(payload, dict) and isinstance(payload.get("cameras"), dict):
        entries = payload["cameras"]
    elif isinstance(payload, dict):
        entries = payload
    else:
        _THRESHOLD_CACHE = {}
        _THRESHOLD_CACHE_KEY = cache_key
        return {}

    parsed: dict[str, tuple[int, int, int]] = {}
    for camera_id, entry in entries.items():
        thresholds = _parse_threshold_entry(entry)
        if thresholds is None:
            continue
        parsed[str(camera_id)] = thresholds

    _THRESHOLD_CACHE = parsed
    _THRESHOLD_CACHE_KEY = cache_key
    return parsed


def _camera_thresholds(camera_id: str | None) -> tuple[int, int, int] | None:
    if not camera_id:
        return None
    return _load_camera_thresholds().get(str(camera_id))


class DensityScorer:
    """Map vehicle counts to density labels using configurable thresholds.

    Buckets (in order of increasing congestion):
        light    -> moderate -> heavy   -> blocked
    """

    def __init__(
        self,
        light: int | None = None,
        moderate: int | None = None,
        heavy: int | None = None,
        camera_id: str | None = None,
    ) -> None:
        camera_light, camera_moderate, camera_heavy = _camera_thresholds(camera_id) or (None, None, None)
        self.light = (
            light
            if light is not None
            else (camera_light if camera_light is not None else settings.density_threshold_light)
        )
        self.moderate = (
            moderate
            if moderate is not None
            else (
                camera_moderate
                if camera_moderate is not None
                else settings.density_threshold_moderate
            )
        )
        self.heavy = (
            heavy
            if heavy is not None
            else (camera_heavy if camera_heavy is not None else settings.density_threshold_heavy)
        )

    def from_count(self, count: int) -> str:
        """Return a density label for the given vehicle count."""
        if count < self.light:
            return "light"
        if count < self.moderate:
            return "moderate"
        if count < self.heavy:
            return "heavy"
        return "blocked"

    def from_coverage(self, coverage_ratio: float) -> str:
        """Return a density label from road-area coverage ratio (0.0–1.0).

        This is a secondary heuristic that can be used when segmentation
        masks are available to estimate how much of the road is occupied.
        """
        if coverage_ratio < 0.10:
            return "light"
        if coverage_ratio < 0.30:
            return "moderate"
        if coverage_ratio < 0.60:
            return "heavy"
        return "blocked"
