"""Tests for time-of-day baseline score adjustment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from trafficcam.analysis.temporal import (
    adjusted_congestion_score,
    baseline_for_bucket,
    density_ordinal,
    hour_bucket_key,
    load_camera_baseline,
    temporal_adjustment,
)


def _history_with(bucket_key: str, scores: list[float]) -> dict:
    return {bucket_key: {"scores": list(scores), "timestamps": [0.0] * len(scores)}}


class TestHourBucketKey:
    def test_weekday_and_hour(self) -> None:
        # 2026-08-20 was a Thursday.
        assert hour_bucket_key("2026-08-20T08:30:00Z") == "thu_08"

    def test_invalid_timestamp_returns_empty(self) -> None:
        assert hour_bucket_key("not-a-date") == ""


class TestBaselineForBucket:
    def test_mean_of_bucket(self) -> None:
        history = _history_with("tue_08", [20.0, 30.0, 40.0, 50.0, 60.0])
        mean, count = baseline_for_bucket(history, "2026-08-25T08:15:00Z")
        assert mean == pytest.approx(40.0)
        assert count == 5

    def test_insufficient_samples_returns_nan(self) -> None:
        history = _history_with("tue_08", [20.0, 30.0])
        mean, count = baseline_for_bucket(history, "2026-08-25T08:15:00Z")
        assert count == 2
        assert mean != mean  # NaN

    def test_missing_bucket(self) -> None:
        mean, count = baseline_for_bucket({}, "2026-08-25T08:15:00Z")
        assert count == 0
        assert mean != mean

    def test_future_and_current_samples_are_excluded(self) -> None:
        target = "2026-08-25T08:15:00Z"
        target_ts = datetime.fromisoformat(target.replace("Z", "+00:00")).timestamp()
        history = {
            "tue_08": {
                "scores": [20.0, 40.0, 90.0],
                "timestamps": [target_ts - 60, target_ts, target_ts + 60],
            }
        }
        mean, count = baseline_for_bucket(history, target)
        assert count == 1
        assert mean != mean


class TestTemporalAdjustment:
    def test_at_baseline_zero_adjustment(self) -> None:
        assert temporal_adjustment(50.0, 50.0, 10.0) == 0.0

    def test_above_baseline_positive(self) -> None:
        # z = +2.0, past the deadband, should yield a positive adjustment.
        assert temporal_adjustment(70.0, 50.0, 10.0) == pytest.approx(6.67, abs=0.05)

    def test_below_baseline_negative(self) -> None:
        assert temporal_adjustment(30.0, 50.0, 10.0) == pytest.approx(-6.67, abs=0.05)

    def test_saturates_at_scale(self) -> None:
        assert temporal_adjustment(100.0, 50.0, 5.0) == pytest.approx(20.0)
        assert temporal_adjustment(0.0, 50.0, 5.0) == pytest.approx(-20.0)

    def test_degenerate_variance_half_strength(self) -> None:
        result = temporal_adjustment(60.0, 50.0, 0.0)
        assert result == pytest.approx(10.0)


class TestAdjustedCongestionScore:
    def test_normal_rush_hour_stays_near_baseline(self) -> None:
        # Camera normally reads ~70 at tue_08; a 72 reading should NOT jump.
        history = _history_with("tue_08", [68.0, 70.0, 71.0, 69.0, 72.0])
        adjusted, meta = adjusted_congestion_score(72.0, history, "2026-08-25T08:00:00Z")
        assert meta["baseline_applied"] is True
        assert adjusted < 75.0

    def test_unusual_spike_pushes_up(self) -> None:
        history = _history_with("wed_14", [20.0] * 8)
        adjusted, meta = adjusted_congestion_score(80.0, history, "2026-08-26T14:00:00Z")
        assert meta["baseline_applied"] is True
        assert meta["adjustment"] == pytest.approx(20.0)
        assert adjusted == 100.0

    def test_insufficient_history_degrades_gracefully(self) -> None:
        adjusted, meta = adjusted_congestion_score(55.0, {}, "2026-08-26T03:00:00Z")
        assert meta["baseline_applied"] is False
        assert "insufficient_history" in meta["reason"]
        assert adjusted == 55.0

    def test_result_clamped_to_valid_range(self) -> None:
        history = _history_with("fri_18", [90.0] * 6)
        adjusted, _ = adjusted_congestion_score(95.0, history, "2026-08-28T18:00:00Z")
        assert 0.0 <= adjusted <= 100.0


class TestLoadCameraBaseline:
    def test_reads_persisted_records(self, tmp_path: Path) -> None:
        cam_dir = tmp_path / "analyses" / "49"
        cam_dir.mkdir(parents=True)
        for idx, score in enumerate([40.0, 42.0, 41.0, 43.0, 44.0]):
            record = {
                "schema_version": 2,
                "camera_id": "49",
                "captured_at": f"2026-08-20T03:0{idx}:00Z",
                "details": {"congestion_score": score, "raw_congestion_score": score},
            }
            (cam_dir / f"20260820030{idx}00.json").write_text(
                json.dumps(record), encoding="utf-8"
            )
        history = load_camera_baseline(tmp_path, "49")
        mean, count = baseline_for_bucket(history, "2026-08-27T03:30:00Z")
        assert count == 5
        assert mean == pytest.approx(42.0)

    def test_missing_camera_returns_empty(self, tmp_path: Path) -> None:
        assert load_camera_baseline(tmp_path, "999") == {}

    def test_failed_observations_are_excluded(self, tmp_path: Path) -> None:
        cam_dir = tmp_path / "analyses" / "49"
        cam_dir.mkdir(parents=True)
        for idx, score in enumerate([40.0, 42.0, 41.0, 43.0, 44.0]):
            record = {
                "schema_version": 2,
                "camera_id": "49",
                "captured_at": f"2026-08-20T03:0{idx}:00Z",
                "details": {"congestion_score": score},
                "health": {"overall": "failed", "usable": False},
            }
            (cam_dir / f"failed{idx}.json").write_text(json.dumps(record), encoding="utf-8")
        history = load_camera_baseline(tmp_path, "49")
        assert history == {}

    def test_camera_cache_isolated_and_raw_score_preferred(self, tmp_path: Path) -> None:
        for camera_id, score in (("49", 40.0), ("50", 80.0)):
            cam_dir = tmp_path / "analyses" / camera_id
            cam_dir.mkdir(parents=True)
            record = {
                "schema_version": 2,
                "camera_id": camera_id,
                "captured_at": "2026-08-20T03:00:00Z",
                "details": {
                    "congestion_score": score + 15.0,
                    "raw_congestion_score": score,
                    "baseline": {"baseline_applied": True},
                },
            }
            (cam_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")

        first = load_camera_baseline(tmp_path, "49")
        second = load_camera_baseline(tmp_path, "50")
        assert first["thu_03"]["scores"] == [40.0]
        assert second["thu_03"]["scores"] == [80.0]

    def test_adjusted_legacy_scores_are_not_baseline_evidence(self, tmp_path: Path) -> None:
        cam_dir = tmp_path / "analyses" / "49"
        cam_dir.mkdir(parents=True)
        record = {
            "camera_id": "49",
            "captured_at": "2026-08-20T03:00:00Z",
            "details": {
                "congestion_score": 70.0,
                "baseline": {"baseline_applied": True},
            },
        }
        (cam_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")
        assert load_camera_baseline(tmp_path, "49") == {}

    def test_unknown_schema_score_is_not_baseline_evidence(self, tmp_path: Path) -> None:
        cam_dir = tmp_path / "analyses" / "49"
        cam_dir.mkdir(parents=True)
        record = {
            "camera_id": "49",
            "captured_at": "2026-08-20T03:00:00Z",
            "details": {
                "congestion_score": 70.0,
                "raw_congestion_score": 60.0,
            },
        }
        (cam_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")
        assert load_camera_baseline(tmp_path, "49") == {}


class TestDensityOrdinal:
    def test_known_levels(self) -> None:
        assert density_ordinal("light") == 0
        assert density_ordinal("blocked") == 3

    def test_unknown_defaults_zero(self) -> None:
        assert density_ordinal("mystery") == 0
        assert density_ordinal(None) == 0
