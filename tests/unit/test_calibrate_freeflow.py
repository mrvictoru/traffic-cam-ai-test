"""Tests for the free-flow calibration backfill tool."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

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
) -> None:
    cam_dir = analyses_root / camera_id
    cam_dir.mkdir(parents=True, exist_ok=True)
    details = {} if speed is None else {"median_speed_px_per_frame": speed}
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
        _write_record(data_dir / "analyses", "49", f"2026-08-20T03:0{idx}:00Z", speed)
    # Daytime sample must be ignored by the default 02-05 window.
    _write_record(data_dir / "analyses", "49", "2026-08-20T12:00:00Z", 4.0)
    # Camera 50: only pre-speed-estimator records (no motion field).
    _write_record(data_dir / "analyses", "50", "2026-08-20T03:00:00Z", None)
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

        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert str(payload["cameras"]["49"]["freeflow_px_per_frame"]) == str(entry["freeflow_px_per_frame"])

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
        _write_record(data_dir / "analyses", "77", "2026-08-20T03:00:00Z", 12.0)
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
        # Window 22..06 wraps midnight; a 23:00 and a 01:00 sample count.
        _write_record(data_dir / "analyses", "61", "2026-08-20T23:00:00Z", 8.0)
        for idx in range(5):
            _write_record(data_dir / "analyses", "61", f"2026-08-21T01:0{idx}:00Z", 8.0 + idx * 0.1)
        # Noon sample excluded even though hour >= start is true for 12 < 22? No —
        # wrapping logic: hour >= 22 or hour < 6. 12 fails both.
        _write_record(data_dir / "analyses", "61", "2026-08-21T12:00:00Z", 40.0)
        config_path = tmp_path / "camera_speed_calibration.json"
        result = calibrate_freeflow.calibrate(
            data_dir, config_path, min_history=5, dry_run=False,
            offpeak_start=22, offpeak_end=6,
        )
        assert "61" in result
        assert result["61"]["freeflow_px_per_frame"] < 20.0
