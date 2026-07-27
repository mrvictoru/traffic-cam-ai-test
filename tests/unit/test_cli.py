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