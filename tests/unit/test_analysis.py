from pathlib import Path

from trafficcam.analysis.metrics import average_confidence
from trafficcam.analysis.scene_classifier import SceneClassifier
from trafficcam.analysis.traffic_detector import TrafficDetector
from trafficcam.api.routes import list_cameras
from trafficcam.storage.database import DatabaseStore
from trafficcam.storage.json_store import JsonStore
from trafficcam.web.app import render_dashboard


def test_analysis_scaffolds_return_simple_results() -> None:
    detector = TrafficDetector()
    classifier = SceneClassifier()
    assert detector.analyze("sample.jpg")["label"] == "unknown"
    assert classifier.classify("sample.jpg")["scene"] == "unknown"


def test_traffic_detector_uses_filename_hint_for_density(tmp_path: Path) -> None:
    image_path = tmp_path / "heavy_traffic.jpg"
    image_path.write_bytes(b"fake-image")

    result = TrafficDetector().analyze(str(image_path))

    assert result["label"] == "heavy"
    assert result["confidence"] >= 0.75


def test_scene_classifier_detects_day_or_night_keywords(tmp_path: Path) -> None:
    night_path = tmp_path / "night_view.jpg"
    night_path.write_bytes(b"fake-image")

    result = SceneClassifier().classify(str(night_path))

    assert result["scene"] == "night"
    assert result["confidence"] >= 0.7


def test_average_confidence_uses_mean_of_results() -> None:
    values = [{"confidence": 0.2}, {"confidence": 0.8}, {"confidence": 1.0}]

    assert average_confidence(values) == 0.6666666666666666


def test_database_store_persists_records(tmp_path: Path) -> None:
    store = DatabaseStore(str(tmp_path / "analytics.db"))

    store.save_records("cameras", [{"camera_id": "cam1", "status": "ok"}])
    rows = store.load_records("cameras")

    assert rows[0]["camera_id"] == "cam1"
    assert rows[0]["status"] == "ok"


def test_api_routes_expose_camera_summaries(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    store.save_json(
        "analyses/cam1/001.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T08:00:00Z",
            "label": "heavy",
            "details": {
                "density": "heavy",
                "flow_rate_vph": {"northbound": 5, "southbound": 6, "total": 11},
            },
        },
    )
    store.save_json(
        "analyses/cam2/001.json",
        {
            "camera_id": "cam2",
            "captured_at": "2026-06-24T09:00:00Z",
            "label": "moderate",
            "details": {
                "density": "moderate",
                "flow_rate_vph": {"northbound": 3, "southbound": 4, "total": 7},
            },
        },
    )

    cameras = list_cameras(store=store)

    assert [camera["camera_id"] for camera in cameras] == ["cam1", "cam2"]
    assert cameras[0]["latest_density"] == "heavy"
    assert cameras[1]["latest_density"] == "moderate"


def test_web_dashboard_renders_camera_summary(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    store.save_json(
        "analyses/cam1/001.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T08:00:00Z",
            "label": "blocked",
            "details": {"density": "blocked"},
        },
    )

    html = render_dashboard(store=store)

    assert "cam1" in html
    assert "blocked" in html
