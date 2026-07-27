from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from trafficcam.api.main import app
from trafficcam.storage.json_store import JsonStore


def _seed_analysis(store: JsonStore, camera_id: str, captured_at: str, density: str, vehicle_count: int) -> None:
    store.save_json(
        f"analyses/{camera_id}/{captured_at.replace(':', '').replace('-', '')}.json",
        {
            "camera_id": camera_id,
            "captured_at": captured_at,
            "label": density,
            "details": {
                "density": density,
                "vehicle_count": vehicle_count,
                "mean_confidence": 0.67,
                "active_tracks": 8,
                "scene": "day",
                "flow_rate_vph": {"northbound": 12, "southbound": 9, "total": 21},
                "per_frame": [
                    {"frame_idx": 0, "vehicle_count": vehicle_count, "density": density}
                ],
                "capture_result": {
                    "name": "Test Camera 49",
                    "district": "澳門區",
                    "sub_district": "新馬路",
                    "stream_url": "https://example.test/live/49.m3u8",
                    "latitude": 22.193,
                    "longitude": 113.541,
                },
            },
        },
    )


def test_api_endpoints_serve_persisted_camera_data(tmp_path: Path, monkeypatch) -> None:
    store = JsonStore(tmp_path / "data")
    _seed_analysis(store, "49", "2026-06-24T08:00:00Z", "moderate", 14)
    _seed_analysis(store, "49", "2026-06-24T09:00:00Z", "heavy", 22)
    _seed_analysis(store, "50", "2026-06-24T09:05:00Z", "light", 5)

    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        health_response = client.get("/health")
        cameras_response = client.get("/api/cameras")
        detail_response = client.get("/api/cameras/49")
        history_response = client.get("/api/cameras/49/history", params={"limit": 2})

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}

    assert cameras_response.status_code == 200
    cameras = cameras_response.json()
    assert [camera["camera_id"] for camera in cameras] == ["49", "50"]
    assert cameras[0]["latest_density"] == "heavy"
    assert cameras[0]["latest_flow_split"] == {"northbound": 12, "southbound": 9, "total": 21}
    assert cameras[0]["map_position"]["source"] == "coordinates"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["camera_id"] == "49"
    assert detail["density"] == "heavy"
    assert detail["vehicle_count"] == 22
    assert detail["stream_url"] == "https://example.test/live/49.m3u8"
    assert detail["map_position"]["latitude"] == 22.193
    assert detail["per_frame"][0]["density"] == "heavy"

    assert history_response.status_code == 200
    history = history_response.json()
    assert [entry["captured_at"] for entry in history] == [
        "2026-06-24T08:00:00Z",
        "2026-06-24T09:00:00Z",
    ]
    assert history[-1]["density"] == "heavy"


def test_api_returns_404_for_unknown_camera(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/cameras/unknown-camera")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown camera: unknown-camera"}
