"""Tests for speed-based congestion estimation."""

from __future__ import annotations

import json

import pytest

from trafficcam.vision.density_scorer import DensityScorer
from trafficcam.vision.speed_estimator import (
    estimate_track_speeds,
    freeflow_for_camera,
    median_track_speed,
    moving_vehicle_count,
    speed_score_from_ratio,
)


def _history(points: list[tuple[int, tuple[float, float]]], track_id: int = 1):
    return [(track_id, idx, pt) for idx, pt in points]


class TestEstimateTrackSpeeds:
    def test_net_displacement_over_frames(self) -> None:
        # 30 px net movement over 3 frames => 10 px/frame.
        history = _history([(0, (0.0, 0.0)), (1, (5.0, 2.0)), (3, (18.0, 24.0))])
        assert estimate_track_speeds([history]) == pytest.approx([10.0])

    def test_skips_single_point_tracks(self) -> None:
        history = _history([(0, (10.0, 10.0))])
        assert estimate_track_speeds([history]) == []

    def test_skips_zero_span_tracks(self) -> None:
        history = _history([(2, (1.0, 1.0)), (2, (9.0, 9.0))])
        assert estimate_track_speeds([history]) == []

    def test_jittery_track_yields_low_speed(self) -> None:
        # Wiggles around a point: net displacement ~0 even though per-step
        # movements are non-trivial.
        history = _history(
            [
                (0, (100.0, 100.0)),
                (1, (103.0, 98.0)),
                (2, (99.0, 101.0)),
                (3, (100.5, 99.5)),
            ]
        )
        speeds = estimate_track_speeds([history])
        assert speeds[0] < 0.5


class TestMedianTrackSpeed:
    def test_median_across_multiple_tracks(self) -> None:
        fast = _history([(0, (0.0, 0.0)), (1, (20.0, 0.0))])   # 20 px/frame
        slow = _history([(0, (0.0, 0.0)), (4, (2.0, 0.0))], track_id=2)  # 0.5 px/frame
        # Median of [20.0, 0.5] is their average.
        assert median_track_speed([fast, slow]) == pytest.approx(10.25)

    def test_returns_none_without_motion_data(self) -> None:
        assert median_track_speed([]) is None
        assert median_track_speed([_history([(0, (1.0, 1.0))])]) is None


class TestMovingVehicleCount:
    def test_counts_only_tracks_above_stationary_threshold(self) -> None:
        moving = _history([(0, (0.0, 0.0)), (1, (5.0, 0.0))])   # 5 px/frame
        stalled = _history([(0, (0.0, 0.0)), (5, (0.5, 0.0))], track_id=2)  # 0.1 px/frame
        assert moving_vehicle_count([moving, stalled]) == 1


class TestSpeedScoreFromRatio:
    def test_free_flow_scores_zero(self) -> None:
        assert speed_score_from_ratio(1.0) == 0.0

    def test_stall_saturates_at_hundred(self) -> None:
        assert speed_score_from_ratio(0.0) == 100.0
        assert speed_score_from_ratio(0.05) == 100.0

    def test_linear_in_between(self) -> None:
        # stall ratio default is 0.15; midpoint maps to ~50.
        mid = speed_score_from_ratio((1.0 + 0.15) / 2)
        assert mid == pytest.approx(50.0, abs=1.0)

    def test_handles_none(self) -> None:
        assert speed_score_from_ratio(None) is None

    def test_ratios_above_free_flow_clamp_to_zero(self) -> None:
        assert speed_score_from_ratio(1.8) == 0.0


class TestFreeflowCalibration:
    def test_reads_calibration_file(self, tmp_path) -> None:
        config = tmp_path / "calibration.json"
        config.write_text(
            json.dumps({"cameras": {"49": {"freeflow_px_per_frame": 12.5}}}),
            encoding="utf-8",
        )
        assert freeflow_for_camera("49", path=config) == pytest.approx(12.5)
        assert freeflow_for_camera("999", path=config) is None

    def test_missing_file_returns_empty(self, tmp_path) -> None:
        assert freeflow_for_camera("49", path=tmp_path / "missing.json") is None

    def test_rejects_non_positive_values(self, tmp_path) -> None:
        config = tmp_path / "calibration.json"
        config.write_text(
            json.dumps({"cameras": {"49": {"freeflow_px_per_frame": 0}}}),
            encoding="utf-8",
        )
        assert freeflow_for_camera("49", path=config) is None


class TestDensityScorerWithSpeed:
    def setup_method(self) -> None:
        self.scorer = DensityScorer(light=5, moderate=15, heavy=30)

    def test_free_flow_traffic_with_many_vehicles_is_light(self) -> None:
        # High occupancy alone would read heavy/blocked; free-flow speed must
        # pull the blended score clearly below the occupancy-only reading.
        with_speed = self.scorer.score(
            coverage_ratio=0.5,
            count=40,
            mean_confidence=0.8,
            speed_component=0.0,
        )
        occupancy_only = self.scorer.score(coverage_ratio=0.5, count=40, mean_confidence=0.8)
        # Speed carries weight 0.6, so free flow removes at least that share
        # of the congestion signal.
        assert with_speed <= occupancy_only * 0.45
        assert self.scorer.label_from_score(with_speed) != "blocked"

    def test_stalled_traffic_with_few_vehicles_is_heavy(self) -> None:
        # Low occupancy would read light on its own; stalled motion should
        # push the blended score up.
        score = self.scorer.score(
            coverage_ratio=0.05,
            count=3,
            mean_confidence=0.8,
            speed_component=100.0,
        )
        label = self.scorer.label_from_score(score)
        assert label in {"heavy", "blocked"}

    def test_without_speed_component_legacy_behavior_preserved(self) -> None:
        legacy = self.scorer.score(coverage_ratio=0.5, count=40, mean_confidence=0.8)
        # No motion data: occupancy-only scoring must remain unchanged.
        expected = self.scorer.score(coverage_ratio=0.5, count=40, mean_confidence=0.8)
        assert legacy == expected

    def test_out_of_range_speed_component_falls_back(self) -> None:
        with_speed = self.scorer.score(
            coverage_ratio=0.5, count=40, mean_confidence=0.8, speed_component=150.0
        )
        without_speed = self.scorer.score(coverage_ratio=0.5, count=40, mean_confidence=0.8)
        assert with_speed == without_speed
