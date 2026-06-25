"""Convert vehicle detection counts into traffic density buckets."""

from __future__ import annotations

from trafficcam.config import settings


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
    ) -> None:
        self.light = light if light is not None else settings.density_threshold_light
        self.moderate = moderate if moderate is not None else settings.density_threshold_moderate
        self.heavy = heavy if heavy is not None else settings.density_threshold_heavy

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
