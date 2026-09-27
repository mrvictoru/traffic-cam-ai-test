from __future__ import annotations

import pytest

from trafficcam.vision.motion import classify_motion


def _history(points: list[tuple[int, tuple[float, float]]], track_id: int = 1):
    return [(track_id, frame, point) for frame, point in points]


def _tracks(speed: float) -> list[list[tuple[int, int, tuple[float, float]]]]:
    return [
        _history([(0, (0.0, 0.0)), (1, (speed, 0.0)), (2, (speed * 2, 0.0))], 1),
        _history([(0, (10.0, 10.0)), (1, (10.0 + speed, 10.0)), (2, (10.0 + speed * 2, 10.0))], 2),
    ]


def _classify(tracks, **kwargs):
    return classify_motion(
        tracks,
        freeflow_px_per_frame=10.0,
        frame_count=10,
        sample_fps=5.0,
        **kwargs,
    )


def test_classifies_free_flow_from_camera_relative_speed() -> None:
    result = _classify(_tracks(8.0))
    assert result.state == "moving_freely"
    assert result.median_ratio == pytest.approx(0.8)
    assert result.eligible_tracks == 2


def test_classifies_slow_traffic() -> None:
    result = _classify(_tracks(3.0))
    assert result.state == "slow"
    assert result.reason == "median_motion_below_freeflow_threshold"


def test_requires_stationary_support_before_stopped_label() -> None:
    result = _classify(_tracks(0.1))
    assert result.state == "stopped"
    assert result.stationary_fraction == 1.0


@pytest.mark.parametrize(
    ("tracks", "kwargs", "reason"),
    [
        ([], {}, "no_tracks"),
        (_tracks(8.0)[:1], {}, "insufficient_track_support"),
        (_tracks(8.0), {"frame_count": 2}, "observation_window_too_short"),
    ],
)
def test_insufficient_evidence_is_unknown(tracks, kwargs, reason) -> None:
    params = {
        "freeflow_px_per_frame": 10.0,
        "frame_count": 10,
        "sample_fps": 5.0,
        **kwargs,
    }
    result = classify_motion(
        tracks,
        **params,
    )
    assert result.state == "unknown"
    assert result.reason == reason


def test_missing_calibration_is_unknown() -> None:
    result = classify_motion(
        _tracks(8.0),
        freeflow_px_per_frame=None,
        frame_count=10,
        sample_fps=5.0,
    )
    assert result.state == "unknown"
    assert result.reason == "freeflow_calibration_unavailable"
    assert result.eligible_tracks == 2
    assert result.eligible_tracks_evaluated is True


def test_invalid_timing_is_unknown() -> None:
    result = classify_motion(
        _tracks(8.0),
        freeflow_px_per_frame=10.0,
        frame_count=10,
        sample_fps=0.0,
    )
    assert result.state == "unknown"
    assert result.reason == "invalid_timing"
