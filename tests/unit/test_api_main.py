from trafficcam.api.main import app, dashboard, health


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
