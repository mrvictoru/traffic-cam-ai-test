from pathlib import Path

import yaml


COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _services() -> dict:
    payload = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return payload["services"]


def test_dashboard_service_disables_pipeline_autostart() -> None:
    dashboard = _services()["macau-feed"]

    assert dashboard["environment"]["PIPELINE_AUTOSTART"] == "0"
    assert dashboard["command"] == ["serve", "--host", "0.0.0.0", "--port", "8000"]
    assert dashboard["ports"] == ["8000:8000"]


def test_live_capture_is_an_explicit_separate_profile() -> None:
    services = _services()
    dashboard = services["macau-feed"]
    live_capture = services["live-capture"]

    assert live_capture["profiles"] == ["capture"]
    assert live_capture["command"][0] == "run-loop"
    assert "--interval" in live_capture["command"]
    assert "${PIPELINE_FRAME_COUNT:-5}" in live_capture["command"]
    assert "ports" not in live_capture
    assert live_capture["volumes"] == dashboard["volumes"]
