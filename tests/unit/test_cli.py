from __future__ import annotations

import json
from pathlib import Path

from trafficcam import cli


def test_package_pipeline_module_exposes_run_pipeline() -> None:
    import trafficcam.pipeline as pipeline

    assert hasattr(pipeline, "run_pipeline")


def test_discover_prints_manifest_and_optionally_writes_file(monkeypatch, capsys, tmp_path: Path) -> None:
    manifest = {"camera_count": 1, "cameras": [{"cam_id": "49"}]}

    class _FakeClient:
        def __init__(self, index_url: str) -> None:
            self.index_url = index_url

        def build_manifest(self, limit=None):
            assert self.index_url == "https://example.test/realtime"
            assert limit == 1
            return manifest

    monkeypatch.setattr(cli, "DSATClient", _FakeClient)
    output_path = tmp_path / "manifest.json"

    result = cli.main(
        [
            "discover",
            "--index-url",
            "https://example.test/realtime",
            "--limit",
            "1",
            "--manifest-file",
            str(output_path),
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == manifest
    assert json.loads(output_path.read_text(encoding="utf-8")) == manifest


def test_run_once_delegates_to_pipeline(monkeypatch, capsys) -> None:
    recorded = {}

    def _fake_dispatch(args, *, interval, max_cycles):
        recorded["command"] = args.command
        recorded["manifest_file"] = args.manifest_file
        recorded["output_dir"] = args.output_dir
        recorded["data_dir"] = args.data_dir
        recorded["frame_count"] = args.frame_count
        recorded["limit"] = args.limit
        recorded["interval"] = interval
        recorded["max_cycles"] = max_cycles
        print(json.dumps({"ok": True}))
        return 0

    monkeypatch.setattr(cli, "_dispatch_run", _fake_dispatch)

    result = cli.main(
        [
            "run-once",
            "--manifest-file",
            "data/manifest.json",
            "--output-dir",
            "output/live",
            "--data-dir",
            "data-live",
            "--frame-count",
            "3",
            "--limit",
            "5",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True}
    assert recorded == {
        "command": "run-once",
        "manifest_file": "data/manifest.json",
        "output_dir": "output/live",
        "data_dir": "data-live",
        "frame_count": 3,
        "limit": 5,
        "interval": 0.0,
        "max_cycles": 1,
    }


def test_run_loop_passes_interval_and_cycles(monkeypatch, capsys) -> None:
    recorded = {}

    def _fake_dispatch(args, *, interval, max_cycles):
        recorded["interval"] = interval
        recorded["max_cycles"] = max_cycles
        print(json.dumps({"loop": True}))
        return 0

    monkeypatch.setattr(cli, "_dispatch_run", _fake_dispatch)

    result = cli.main(["run-loop", "--interval", "15", "--max-cycles", "4"])

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {"loop": True}
    assert recorded == {"interval": 15.0, "max_cycles": 4}


def test_audit_config_reports_missing_camera_config(monkeypatch, capsys, tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cameras": [
                    {"cam_id": "49", "name": "Camera 49", "district": "A", "sub_district": "A1"},
                    {"cam_id": "50", "name": "Camera 50", "district": "A", "sub_district": "A2"},
                    {"cam_id": "59", "name": "Camera 59", "district": "B", "sub_district": "B1"},
                ]
            }
        ),
        encoding="utf-8",
    )
    coordinates_path = tmp_path / "camera_coordinates.json"
    coordinates_path.write_text(
        json.dumps({"cameras": {"49": {"latitude": 22.1, "longitude": 113.5}}}),
        encoding="utf-8",
    )
    thresholds_path = tmp_path / "camera_density_thresholds.json"
    thresholds_path.write_text(
        json.dumps({"cameras": {"49": {"light": 4, "moderate": 10, "heavy": 16}, "50": {"light": 4, "moderate": 10, "heavy": 16}}}),
        encoding="utf-8",
    )
    calibration_path = tmp_path / "camera_speed_calibration.json"
    calibration_path.write_text(
        json.dumps({"cameras": {"49": {"freeflow_px_per_frame": 10.5}}}),
        encoding="utf-8",
    )
    rois_path = tmp_path / "camera_rois.json"
    rois_path.write_text(
        json.dumps({"49": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]}),
        encoding="utf-8",
    )
    flow_lines_path = tmp_path / "camera_flow_lines.json"
    flow_lines_path.write_text(
        json.dumps({"50": {"start": [0.0, 0.5], "end": [1.0, 0.5]}}),
        encoding="utf-8",
    )
    analyses_dir = tmp_path / "data" / "analyses"
    analyses_dir.mkdir(parents=True)
    (analyses_dir / "50").mkdir()
    (analyses_dir / "50" / "20260819T180000Z.json").write_text(
        json.dumps(
            {
                "camera_id": "50",
                # 18:00 UTC is 02:00 the following day in Asia/Macau.
                "captured_at": "2026-08-19T18:00:00Z",
                "details": {"median_speed_px_per_frame": 8.0},
            }
        ),
        encoding="utf-8",
    )
    (analyses_dir / "59").mkdir()
    (analyses_dir / "59" / "20260819T180000Z.json").write_text(
        json.dumps(
            {
                "camera_id": "59",
                "captured_at": "2026-08-19T18:00:00Z",
                "details": {},
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "audit.json"

    result = cli.main(
        [
            "audit-config",
            "--manifest-file",
            str(manifest_path),
            "--coordinates-file",
            str(coordinates_path),
            "--thresholds-file",
            str(thresholds_path),
            "--calibration-file",
            str(calibration_path),
            "--data-dir",
            str(tmp_path / "data"),
            "--calibration-min-history",
            "1",
            "--rois-file",
            str(rois_path),
            "--flow-lines-file",
            str(flow_lines_path),
            "--report-file",
            str(report_path),
            "--queue-limit",
            "2",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["camera_count"] == 3
    assert payload["fully_configured_count"] == 0
    assert payload["missing_counts"] == {
        "coordinates": 2,
        "thresholds": 1,
        "speed_calibration": 2,
        "rois": 2,
        "flow_lines": 2,
    }
    assert payload["missing_camera_ids"]["coordinates"] == ["50", "59"]
    assert payload["missing_camera_ids"]["thresholds"] == ["59"]
    assert payload["missing_camera_ids"]["speed_calibration"] == ["50", "59"]
    assert payload["missing_camera_ids"]["rois"] == ["50", "59"]
    assert payload["missing_camera_ids"]["flow_lines"] == ["49", "59"]
    assert payload["speed_calibration"]["configured_camera_ids"] == ["49"]
    assert payload["speed_calibration"]["status_counts"] == {
        "calibrated": 1,
        "missing_motion_history": 1,
        "ready": 1,
    }
    assert payload["speed_calibration"]["status_camera_ids"]["ready"] == ["50"]
    assert payload["human_calibration"]["human_required"] is True
    assert payload["human_calibration"]["gaps"]["missing_coordinates"] == 2
    assert payload["config_files"]["corridors"].endswith("camera_corridors.json")
    assert payload["next_calibration_queue"] == [
        {
            "camera_id": "49",
            "name": "Camera 49",
            "district": "A",
            "sub_district": "A1",
            "missing": ["flow_lines"],
            "missing_count": 1,
        },
        {
            "camera_id": "50",
            "name": "Camera 50",
            "district": "A",
            "sub_district": "A2",
            "missing": ["coordinates", "rois"],
            "missing_count": 2,
        },
    ]
    assert json.loads(report_path.read_text(encoding="utf-8")) == payload


def test_calibrate_freeflow_command_runs_and_prints_result(monkeypatch, capsys, tmp_path: Path) -> None:
    recorded = {}

    def _fake_calibrate(data_dir, config_path, min_history, dry_run, offpeak_start=2, offpeak_end=5):
        recorded["data_dir"] = data_dir
        recorded["config_path"] = config_path
        recorded["min_history"] = min_history
        recorded["dry_run"] = dry_run
        recorded["offpeak_start"] = offpeak_start
        recorded["offpeak_end"] = offpeak_end
        return {"49": {"freeflow_px_per_frame": 10.5, "sample_count": 6, "offpeak_hours": "02-05"}}

    monkeypatch.setattr(cli, "calibrate", _fake_calibrate)

    result = cli.main(
        [
            "calibrate-freeflow",
            "--data-dir",
            str(tmp_path / "data"),
            "--config",
            str(tmp_path / "camera_speed_calibration.json"),
            "--min-history",
            "7",
            "--offpeak-start",
            "1",
            "--offpeak-end",
            "4",
            "--dry-run",
        ]
    )

    assert result == 0
    assert recorded["data_dir"] == tmp_path / "data"
    assert recorded["config_path"] == tmp_path / "camera_speed_calibration.json"
    assert recorded["min_history"] == 7
    assert recorded["dry_run"] is True
    assert recorded["offpeak_start"] == 1
    assert recorded["offpeak_end"] == 4
    assert json.loads(capsys.readouterr().out) == {
        "data_dir": str(tmp_path / "data"),
        "config": str(tmp_path / "camera_speed_calibration.json"),
        "dry_run": True,
        "camera_count": 1,
        "cameras": {"49": {"freeflow_px_per_frame": 10.5, "sample_count": 6, "offpeak_hours": "02-05"}},
    }


def test_serve_dispatches_to_uvicorn(monkeypatch) -> None:
    recorded = {}

    def _fake_serve(args):
        recorded["host"] = args.host
        recorded["port"] = args.port
        recorded["reload"] = args.reload
        return 0

    monkeypatch.setattr(cli, "_dispatch_serve", _fake_serve)

    result = cli.main(["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"])

    assert result == 0
    assert recorded == {"host": "0.0.0.0", "port": 9000, "reload": True}