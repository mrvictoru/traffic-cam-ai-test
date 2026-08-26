from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trafficcam.api.main import app
from trafficcam.storage.json_store import JsonStore


def _seed_analysis(
    store: JsonStore,
    camera_id: str,
    captured_at: str,
    density: str,
    vehicle_count: int,
    *,
    latitude: float = 22.193,
    longitude: float = 113.541,
) -> None:
    store.save_json(
        f"analyses/{camera_id}/{captured_at.replace(':', '').replace('-', '')}.json",
        {
            "camera_id": camera_id,
            "captured_at": captured_at,
            "label": density,
            "details": {
                "density": density,
                "vehicle_count": vehicle_count,
                "congestion_score": min(100.0, vehicle_count * 3.0),
                "coverage_ratio": 0.12,
                "mean_confidence": 0.67,
                "active_tracks": 8,
                "scene": "day",
                "flow_rate_vph": {"northbound": 12, "southbound": 9, "total": 21},
                "per_frame": [
                    {
                        "frame_idx": 0,
                        "image_path": f"output/live-validation/cam_{camera_id}/frame_001.jpg",
                        "vehicle_count": vehicle_count,
                        "density": density,
                    }
                ],
                "capture_result": {
                    "name": "Test Camera 49",
                    "district": "澳門區",
                    "sub_district": "新馬路",
                    "stream_url": "https://example.test/live/49.m3u8",
                    "latitude": latitude,
                    "longitude": longitude,
                    "debug_frames_dir": f"output/live-validation/cam_{camera_id}/debug",
                },
            },
        },
    )


def test_api_endpoints_serve_persisted_camera_data(tmp_path: Path, monkeypatch) -> None:
    store = JsonStore(tmp_path / "data")
    frame_path = tmp_path / "output" / "live-validation" / "cam_49" / "frame_001.jpg"
    frame_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path.write_bytes(b"frame")
    debug_path = tmp_path / "output" / "live-validation" / "cam_49" / "debug" / "frame_001_tracked.jpg"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    debug_path.write_bytes(b"debug")
    _seed_analysis(store, "49", "2026-06-24T08:00:00Z", "moderate", 14)
    _seed_analysis(store, "49", "2026-06-24T09:00:00Z", "heavy", 22)
    _seed_analysis(store, "50", "2026-06-24T09:05:00Z", "light", 5)

    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        health_response = client.get("/health")
        cameras_response = client.get("/api/cameras")
        detail_response = client.get("/api/cameras/49")
        history_response = client.get("/api/cameras/49/history", params={"limit": 2})
        frame_response = client.get("/output/live-validation/cam_49/frame_001.jpg")
        debug_response = client.get("/output/live-validation/cam_49/debug/frame_001_tracked.jpg")

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
    assert detail["latest_frame_url"].startswith("/output/live-validation/cam_49/frame_001.jpg?v=")
    assert detail["latest_debug_frame_url"].startswith("/output/live-validation/cam_49/debug/frame_001_tracked.jpg?v=")
    assert detail["latest_image_url"].startswith("/output/live-validation/cam_49/debug/frame_001_tracked.jpg?v=")
    assert detail["per_frame"][0]["image_url"].startswith("/output/live-validation/cam_49/frame_001.jpg?v=")
    assert detail["per_frame"][0]["display_image_url"].startswith("/output/live-validation/cam_49/debug/frame_001_tracked.jpg?v=")

    assert frame_response.status_code == 200
    assert frame_response.content == b"frame"
    assert debug_response.status_code == 200
    assert debug_response.content == b"debug"

    assert history_response.status_code == 200
    history = history_response.json()
    assert [entry["captured_at"] for entry in history] == [
        "2026-06-24T08:00:00Z",
        "2026-06-24T09:00:00Z",
    ]
    assert history[-1]["density"] == "heavy"
    assert history[-1]["congestion_score"] == 66.0


def test_api_overview_endpoint(tmp_path: Path, monkeypatch) -> None:
    store = JsonStore(tmp_path / "data")
    _seed_analysis(store, "49", "2026-06-24T09:00:00Z", "heavy", 22, latitude=22.193, longitude=113.541)
    _seed_analysis(store, "50", "2026-06-24T09:05:00Z", "light", 5, latitude=22.1942, longitude=113.544)
    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/overview")

    assert response.status_code == 200
    overview = response.json()
    assert overview["camera_count"] == 2
    counts = overview["density_counts"]
    assert counts["heavy"] == 1
    assert counts["light"] == 1
    assert overview["average_score"] is not None
    worst_ids = [cam["camera_id"] for cam in overview["worst_cameras"]]
    assert worst_ids[0] == "49"
    assert len(overview["corridor_segments"]) == 1
    assert overview["corridor_segments"][0]["camera_ids"] == ["49", "50"]
    assert overview["calibration_summary"]["configured"] == 0
    assert overview["calibration_summary"]["missing"] == 2


def test_api_returns_404_for_unknown_camera(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)

    with TestClient(app) as client:
        response = client.get("/api/cameras/unknown-camera")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown camera: unknown-camera"}
