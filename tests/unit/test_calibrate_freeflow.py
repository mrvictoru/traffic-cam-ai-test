"""Tests for the free-flow calibration backfill tool."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from trafficcam.calibration import calibrate_with_report, summarize_calibration_coverage

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
_spec = importlib.util.spec_from_file_location("calibrate_freeflow", _TOOLS_DIR / "calibrate_freeflow.py")
calibrate_freeflow = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("calibrate_freeflow", calibrate_freeflow)
_spec.loader.exec_module(calibrate_freeflow)


def _write_record(
    analyses_root: Path,
    camera_id: str,
    captured_at: str,
    speed: float | None,
    *,
    confidence: float = 0.9,
    active_tracks: int = 3,
    eligible_tracks: int = 3,
    support_evaluated: bool = True,
    detector_model: str = "yolo11s.pt",
    per_frame: list[dict] | None = None,
) -> None:
    cam_dir = analyses_root / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    details = {
        "mean_confidence": confidence,
        "active_tracks": active_tracks,
        "detector_model": detector_model,
        "motion_support": {
            "eligible_tracks": eligible_tracks,
            "eligible_tracks_evaluated": support_evaluated,
        },
    }
    if per_frame is not None:
        details["per_frame"] = per_frame
    if speed is not None:
        details["median_speed_px_per_frame"] = speed
    (cam_dir / f"{captured_at.replace(':', '')}.json").write_text(
        json.dumps({"camera_id": camera_id, "captured_at": captured_at, "details": details}),
        encoding="utf-8",
    )


@pytest.fixture()
def history_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    # Camera 49: 6 off-peak samples with a clear free-flow cluster plus one outlier.
    offpeak_speeds = [10.0, 10.5, 11.0, 10.2, 9.8, 30.0]
    for idx, speed in enumerate(offpeak_speeds):
        # 19:xx UTC is 03:xx the following day in Macau.
        _write_record(data_dir / "analyses", "49", f"2026-08-19T19:0{idx}:00Z", speed)
    # 04:00 UTC is noon in Macau and must be ignored by the 02-05 local window.
    _write_record(data_dir / "analyses", "49", "2026-08-20T04:00:00Z", 4.0)
    # Camera 50: only pre-speed-estimator records (no motion field).
    _write_record(data_dir / "analyses", "50", "2026-08-19T19:00:00Z", None)
    return data_dir


class TestCalibrate:
    def test_writes_freeflow_calibration(self, history_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(history_dir, config_path, min_history=5, dry_run=False)

        assert "49" in result
        entry = result["49"]
        assert entry["freeflow_px_per_frame"] == pytest.approx(11.0, abs=0.8)
        # The 30 px/frame jitter outlier must be trimmed from the sample set.
        assert entry["sample_count"] == 5
        assert entry["sampling_window_local"] == "02:00-05:00 Asia/Macau"

        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert str(payload["cameras"]["49"]["freeflow_px_per_frame"]) == str(entry["freeflow_px_per_frame"])
        assert payload["cameras"]["49"]["sampling_window_local"] == "02:00-05:00 Asia/Macau"
        assert "offpeak_hours" not in payload["cameras"]["49"]

    def test_daytime_samples_excluded(self, history_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_path / "camera_speed_calibration.json"
        calibrate_freeflow.calibrate(history_dir, config_path, min_history=5, dry_run=False)
        # If the 12:00 sample (4.0 px/frame) leaked in, the percentile would drop.
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert payload["cameras"]["49"]["freeflow_px_per_frame"] > 9.0

    def test_camera_without_motion_data_is_skipped(self, history_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(history_dir, config_path, min_history=1, dry_run=False)
        assert "50" not in result

    def test_insufficient_history_skipped(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        _write_record(data_dir / "analyses", "77", "2026-08-19T19:00:00Z", 12.0)
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(data_dir, config_path, min_history=5, dry_run=False)
        assert "77" not in result

    def test_dry_run_does_not_write(self, history_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(history_dir, config_path, min_history=5, dry_run=True)
        assert result
        assert not config_path.exists()

    def test_merges_with_existing_entries(self, history_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_path / "camera_speed_calibration.json"
        config_path.write_text(
            json.dumps({"cameras": {"99": {"freeflow_px_per_frame": 7.5}}}),
            encoding="utf-8",
        )
        calibrate_freeflow.calibrate(history_dir, config_path, min_history=5, dry_run=False)
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert "99" in payload["cameras"]
        assert "49" in payload["cameras"]

    def test_wrapping_offpeak_window(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        # Window 22..06 Macau time wraps midnight; 15:00 and 17:00 UTC map to
        # 23:00 and 01:00 local respectively.
        _write_record(data_dir / "analyses", "61", "2026-08-20T15:00:00Z", 8.0)
        for idx in range(5):
            _write_record(data_dir / "analyses", "61", f"2026-08-20T17:0{idx}:00Z", 8.0 + idx * 0.1)
        # 04:00 UTC is noon in Macau and fails both sides of the wrapped window.
        _write_record(data_dir / "analyses", "61", "2026-08-21T04:00:00Z", 40.0)
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(
            data_dir, config_path, min_history=5, dry_run=False,
            offpeak_start=22, offpeak_end=6,
        )
        assert "61" in result
        assert result["61"]["freeflow_px_per_frame"] < 20.0
        assert result["61"]["sampling_window_local"] == "22:00-06:00 Asia/Macau"

    def test_utc_timestamps_use_macau_local_offpeak_hours(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        # 19:00 UTC is 03:00 the following day in Macau and must be included.
        for idx in range(5):
            _write_record(
                data_dir / "analyses",
                "88",
                f"2026-08-20T19:0{idx}:00Z",
                10.0 + idx * 0.1,
            )
        # 03:00 UTC is 11:00 in Macau and must not be treated as off-peak.
        for idx in range(5):
            _write_record(
                data_dir / "analyses",
                "88",
                f"2026-08-20T03:1{idx}:00Z",
                40.0 + idx,
            )

        result = calibrate_freeflow.calibrate(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=5,
            dry_run=True,
        )

        assert result["88"]["sample_count"] == 5
        assert result["88"]["freeflow_px_per_frame"] < 20.0

    def test_quality_filters_and_rejection_counts(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        analyses = data_dir / "analyses"
        for idx, speed in enumerate((10.0, 11.0, 12.0)):
            _write_record(analyses, "72", f"2026-08-19T19:0{idx}:00Z", speed)
        _write_record(
            analyses,
            "72",
            "2026-08-19T19:03:00Z",
            100.0,
            confidence=0.1,
        )
        _write_record(
            analyses,
            "72",
            "2026-08-19T19:04:00Z",
            100.0,
            eligible_tracks=1,
        )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=3,
            dry_run=True,
        )

        assert result["cameras"]["72"]["sample_count"] == 3
        assert result["evidence"]["72"]["quality_qualified_records"] == 3
        assert result["evidence"]["72"]["rejected"]["low_confidence"] == 1
        assert result["evidence"]["72"]["rejected"]["insufficient_track_support"] == 1

    def test_requires_evaluated_eligible_track_support(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        analyses = data_dir / "analyses"
        _write_record(
            analyses,
            "72",
            "2026-08-19T19:00:00Z",
            10.0,
            support_evaluated=False,
        )
        old_record = analyses / "72" / "2026-08-19T19:01:00Z.json"
        old_record.write_text(
            json.dumps(
                {
                    "camera_id": "72",
                    "captured_at": "2026-08-19T19:01:00Z",
                    "details": {
                        "median_speed_px_per_frame": 10.0,
                        "mean_confidence": 0.9,
                        "active_tracks": 20,
                        "detector_model": "yolo11s.pt",
                    },
                }
            ),
            encoding="utf-8",
        )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=1,
            dry_run=True,
        )

        assert result["cameras"] == {}
        assert result["evidence"]["72"]["rejected"]["missing_track_support"] == 2

    def test_rejects_records_from_a_different_detector_model(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        _write_record(
            data_dir / "analyses",
            "72",
            "2026-08-19T19:00:00Z",
            10.0,
            detector_model="yolov8n.pt",
        )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=1,
            dry_run=True,
            detector_model="yolo11s.pt",
        )

        assert result["cameras"] == {}
        assert result["evidence"]["72"]["rejected"]["detector_model_mismatch"] == 1

    def test_reports_chronological_half_stability(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        for idx, speed in enumerate((10.0, 10.2, 10.4, 10.6, 10.8, 20.0, 20.2, 20.4, 20.6, 20.8)):
            _write_record(
                data_dir / "analyses",
                "73",
                f"2026-08-19T19:{idx:02d}:00Z",
                speed,
            )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=5,
            dry_run=True,
        )
        halves = result["evidence"]["73"]["chronological_halves"]

        assert halves["first"]["sample_count"] == 5
        assert halves["second"]["sample_count"] == 5
        assert halves["p95_ratio"] == pytest.approx(2.0, abs=0.1)
        assert halves["review_status"] == "review_required"

    def test_low_quality_history_is_not_ready(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        _write_record(
            data_dir / "analyses",
            "74",
            "2026-08-19T19:00:00Z",
            10.0,
            confidence=0.1,
            active_tracks=0,
        )

        coverage = summarize_calibration_coverage(
            ["74"],
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=1,
        )

        assert coverage["status_camera_ids"]["low_quality_history"] == ["74"]

    def test_occupied_frames_are_not_diluted_by_empty_frames(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        per_frame = [{"vehicle_count": 0, "confidence": 0.0} for _ in range(20)]
        per_frame.extend(
            {"vehicle_count": 2, "confidence": 0.8} for _ in range(5)
        )
        for idx in range(5):
            _write_record(
                data_dir / "analyses",
                "59",
                f"2026-08-19T19:0{idx}:00Z",
                8.0 + (idx * 0.1),
                confidence=0.16,
                per_frame=per_frame,
            )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=5,
            dry_run=True,
        )

        assert result["cameras"]["59"]["sample_count"] == 5
        assert result["evidence"]["59"]["rejected"]["low_confidence"] == 0
        assert result["evidence"]["59"]["confidence_basis_counts"] == {"occupied_frames": 5}
        assert result["evidence"]["59"]["mean_sample_confidence"] == pytest.approx(0.8, abs=0.01)

    def test_stopped_dominated_window_is_not_persisted(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        speeds = [0.1, 0.15, 0.2, 0.2, 0.25, 0.3, 0.35, 6.0, 6.5, 7.0]
        for idx, speed in enumerate(speeds):
            _write_record(
                data_dir / "analyses",
                "62",
                f"2026-08-19T19:{idx:02d}:00Z",
                speed,
            )

        result = calibrate_with_report(
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=5,
            dry_run=False,
        )

        assert "62" not in result["cameras"]
        evidence = result["evidence"]["62"]
        assert evidence["persistence_block"] == "stopped_dominated"
        assert evidence["raw_p95_px_per_frame"] > 5.0
        assert not (tmp_path / "camera_speed_calibration.json").exists()

        coverage = summarize_calibration_coverage(
            ["62"],
            data_dir,
            tmp_path / "camera_speed_calibration.json",
            min_history=5,
        )
        assert coverage["status_camera_ids"]["stopped_dominated"] == ["62"]
