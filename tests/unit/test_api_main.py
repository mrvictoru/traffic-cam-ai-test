from trafficcam.api.main import _autostart_enabled, _autostart_limit, _live_loop_kwargs, app, dashboard, health


def test_app_exposes_dashboard_health_and_cameras_endpoints() -> None:
    paths = set(app.openapi()["paths"].keys())

    assert "/" in paths
    assert "/health" in paths
    assert "/api/cameras" in paths
    assert "/api/cameras/{camera_id}" in paths
    assert "/api/cameras/{camera_id}/history" in paths


def test_dashboard_endpoint_returns_html() -> None:
    response = dashboard()

    assert response.media_type == "text/html"
    assert b"leaflet" in response.body.lower()
    assert b"Macau Traffic Congestion" in response.body


def test_health_endpoint_returns_ok() -> None:
    assert health() == {"status": "ok"}


def test_autostart_helpers_use_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PIPELINE_AUTOSTART", raising=False)
    monkeypatch.delenv("PIPELINE_MANIFEST_FILE", raising=False)
    monkeypatch.delenv("PIPELINE_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("PIPELINE_DATA_DIR", raising=False)
    monkeypatch.delenv("PIPELINE_LIMIT", raising=False)

    assert _autostart_enabled() is False
    assert _autostart_limit() is None
    assert _live_loop_kwargs() == {
        "manifest_file": "data/manifest.json",
        "output_dir": "output/live",
        "data_dir": "data",
        "frame_count": 1,
        "limit": None,
    }


def test_autostart_helpers_respect_environment(monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_AUTOSTART", "true")
    monkeypatch.setenv("PIPELINE_MANIFEST_FILE", "data/temp_manifest_25.json")
    monkeypatch.setenv("PIPELINE_OUTPUT_DIR", "output/live")
    monkeypatch.setenv("PIPELINE_DATA_DIR", "data")
    monkeypatch.setenv("PIPELINE_LIMIT", "25")

    assert _autostart_enabled() is True
    assert _autostart_limit() == 25
    assert _live_loop_kwargs() == {
        "manifest_file": "data/temp_manifest_25.json",
        "output_dir": "output/live",
        "data_dir": "data",
        "frame_count": 1,
        "limit": 25,
    }
