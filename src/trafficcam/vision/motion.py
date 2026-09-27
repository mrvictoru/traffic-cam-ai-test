"""Camera-relative qualitative traffic motion classification."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .speed_estimator import TrackHistory, estimate_track_speeds


@dataclass(frozen=True)
class MotionAssessment:
    """A conservative motion label with the evidence used to derive it."""

    state: str
    reason: str
    median_ratio: float | None
    eligible_tracks: int
    total_tracks: int
    observed_seconds: float
    stationary_fraction: float | None
    eligible_tracks_evaluated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_motion(
    track_histories: list[TrackHistory] | dict[int, TrackHistory],
    *,
    freeflow_px_per_frame: float | None,
    frame_count: int,
    sample_fps: float | None,
    min_track_points: int = 3,
    min_tracks: int = 2,
    min_observed_seconds: float = 1.5,
    slow_ratio: float = 0.15,
    freeflow_ratio: float = 0.60,
    stopped_fraction: float = 0.60,
) -> MotionAssessment:
    """Classify observed traffic as moving freely, slow, stopped, or unknown.

    The input speed is pixel displacement per frame and is normalized only by
    a same-camera free-flow reference. Short or sparsely tracked bursts remain
    unknown rather than being treated as stopped traffic.
    """
    histories = (
        list(track_histories.values())
        if isinstance(track_histories, dict)
        else list(track_histories or [])
    )
    total_tracks = len(histories)
    fps = float(sample_fps or 0.0)
    observed_seconds = (
        (max(0, int(frame_count) - 1) / fps) if fps > 0 else 0.0
    )
    if not histories:
        return MotionAssessment(
            "unknown",
            "no_tracks",
            None,
            0,
            total_tracks,
            observed_seconds,
            None,
            True,
        )

    eligible = [
        history
        for history in histories
        if len(history) >= min_track_points
    ]
    speeds = estimate_track_speeds(eligible)
    eligible_track_count = len(speeds)

    if (
        freeflow_px_per_frame is None
        or not math.isfinite(freeflow_px_per_frame)
        or freeflow_px_per_frame <= 0
    ):
        return MotionAssessment(
            "unknown",
            "freeflow_calibration_unavailable",
            None,
            eligible_track_count,
            total_tracks,
            observed_seconds,
            None,
            True,
        )
    if not math.isfinite(fps) or fps <= 0 or frame_count < 2:
        return MotionAssessment(
            "unknown",
            "invalid_timing",
            None,
            eligible_track_count,
            total_tracks,
            observed_seconds,
            None,
            True,
        )
    if observed_seconds < min_observed_seconds:
        return MotionAssessment(
            "unknown",
            "observation_window_too_short",
            None,
            eligible_track_count,
            total_tracks,
            observed_seconds,
            None,
            True,
        )

    if len(speeds) < min_tracks:
        return MotionAssessment(
            "unknown",
            "insufficient_track_support",
            None,
            len(speeds),
            total_tracks,
            observed_seconds,
            None,
            True,
        )

    ratios = [max(0.0, speed / freeflow_px_per_frame) for speed in speeds]
    ratios.sort()
    midpoint = len(ratios) // 2
    median_ratio = (
        ratios[midpoint]
        if len(ratios) % 2
        else (ratios[midpoint - 1] + ratios[midpoint]) / 2
    )
    stationary_fraction = sum(ratio < slow_ratio for ratio in ratios) / len(ratios)
    if stationary_fraction >= stopped_fraction and median_ratio < slow_ratio:
        state = "stopped"
        reason = "most_tracks_below_slow_threshold"
    elif median_ratio < freeflow_ratio:
        state = "slow"
        reason = "median_motion_below_freeflow_threshold"
    else:
        state = "moving_freely"
        reason = "median_motion_at_or_above_freeflow_threshold"

    return MotionAssessment(
        state,
        reason,
        round(median_ratio, 4),
        len(speeds),
        total_tracks,
        round(observed_seconds, 3),
        round(stationary_fraction, 4),
        True,
    )
