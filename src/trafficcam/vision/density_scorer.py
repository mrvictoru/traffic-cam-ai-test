"""Convert vehicle detection signals into traffic density buckets and a continuous congestion score."""

from __future__ import annotations

import json
import os
from pathlib import Path

from trafficcam.config import settings


_THRESHOLD_CACHE: dict[str, tuple[int, int, int]] | None = None
_THRESHOLD_CACHE_KEY: tuple[str, int] | None = None

# Hybrid score weights (sum to 1.0). Coverage of road area is the primary
# signal because it normalizes across camera angles/distances; count adds
# absolute density; confidence penalizes unreliable detections.
SCORE_WEIGHT_COVERAGE = float(os.getenv("SCORE_WEIGHT_COVERAGE", "0.5"))
SCORE_WEIGHT_COUNT = float(os.getenv("SCORE_WEIGHT_COUNT", "0.3"))
SCORE_WEIGHT_CONFIDENCE = float(os.getenv("SCORE_WEIGHT_CONFIDENCE", "0.2"))

# Continuous 0-100 score boundaries used to derive a label from the score.
_SCORE_LIGHT_MAX = float(os.getenv("CONGESTION_SCORE_LIGHT_MAX", "25.0"))
_SCORE_MODERATE_MAX = float(os.getenv("CONGESTION_SCORE_MODERATE_MAX", "50.0"))
_SCORE_HEAVY_MAX = float(os.getenv("CONGESTION_SCORE_HEAVY_MAX", "75.0"))

# Coverage ratio at which the road is considered fully saturated (score 100
# from the coverage component). Vehicle boxes overlap heavily in jams, so a
# ratio below 1.0 is realistic for "blocked".
COVERAGE_SATURATION = float(os.getenv("CONGESTION_COVERAGE_SATURATION", "0.6"))
# Mean detection confidence at or above which signals are fully trusted;
# below this, scores are progressively discounted (half trust at 0).
CONFIDENCE_FULL_TRUST = float(os.getenv("CONGESTION_CONFIDENCE_FULL_TRUST", "0.45"))

_DENSITY_LEVELS = ("light", "moderate", "heavy", "blocked")


def clamp01(value: float) -> float:
    """Clamp a value into [0.0, 1.0]."""
    return max(0.0, min(1.0, float(value)))


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

    @staticmethod
    def label_from_score(score: float) -> str:
        """Map a continuous 0-100 congestion score onto a density label."""
        if score < _SCORE_LIGHT_MAX:
            return "light"
        if score < _SCORE_MODERATE_MAX:
            return "moderate"
        if score < _SCORE_HEAVY_MAX:
            return "heavy"
        return "blocked"

    def score(
        self,
        coverage_ratio: float | None = None,
        count: int | None = None,
        mean_confidence: float | None = None,
    ) -> float:
        """Compute a continuous 0-100 congestion score.

        Hybrid blend of:
        - coverage_ratio: fraction of ROI/road area covered by vehicle boxes
          (weight SCORE_WEIGHT_COVERAGE; normalized against a saturation point
          where roads are considered fully jammed).
        - normalized count: per-frame mean vehicle count scaled by this
          scorer's `heavy` threshold as the saturation point (weight
          SCORE_WEIGHT_COUNT).
        - confidence factor: scales up the other two when detections are
          reliable; low-confidence frames contribute less signal rather than
          being trusted at face value (weight SCORE_WEIGHT_CONFIDENCE).

        When coverage is unavailable the full weight redistributes to count.
        """
        w_cov = SCORE_WEIGHT_COVERAGE if coverage_ratio is not None else 0.0
        w_cnt = min(1.0 - w_cov, max(SCORE_WEIGHT_COUNT, 1.0 - w_cov))
        total_w = w_cov + w_cnt
        if total_w <= 0:
            return 0.0

        cov_component = clamp01(coverage_ratio / COVERAGE_SATURATION) * 100.0 if coverage_ratio is not None else 0.0
        cnt_saturation = max(1, self.heavy)
        cnt_component = clamp01((count or 0) / cnt_saturation) * 100.0

        base = (w_cov * cov_component + w_cnt * cnt_component) / total_w
        if mean_confidence is None or mean_confidence <= 0:
            conf_factor = 1.0 if (count or 0) == 0 else 0.5
        elif (count or 0) == 0:
            conf_factor = 1.0
        else:
            # Full trust at or above CONFIDENCE_FULL_TRUST; below that,
            # progressively discount down to half trust at zero confidence.
            ratio = clamp01(mean_confidence / CONFIDENCE_FULL_TRUST)
            conf_factor = 1.0 if ratio >= 1.0 else 0.5 + 0.5 * ratio
        return round(clamp01(base * conf_factor / 100.0) * 100.0, 2)
