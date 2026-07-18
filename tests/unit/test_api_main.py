from trafficcam.api.main import app, dashboard, health


def test_app_exposes_dashboard_health_and_cameras_endpoints() -> None:
    paths = set(app.openapi()["paths"].keys())

    assert "/" in paths
    assert "/health" in paths
    assert "/api/cameras" in paths


def test_dashboard_endpoint_returns_html() -> None:
    response = dashboard()

    assert response.media_type == "text/html"
    assert b"Traffic Cam Dashboard" in response.body


def test_health_endpoint_returns_ok() -> None:
    assert health() == {"status": "ok"}
