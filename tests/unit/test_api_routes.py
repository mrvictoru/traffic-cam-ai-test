from importlib import reload
from pathlib import Path

import pytest
from fastapi import HTTPException

import trafficcam.api.routes as routes
from trafficcam.storage.json_store import JsonStore


@pytest.fixture(autouse=True)
def _isolate_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the manifest loader at an empty temp path.

    The tests call ``reload(routes)``, which re-reads ``CAMERA_MANIFEST_PATH``
    from the environment; without this, the repo's real data/manifest.json
    would leak extra cameras into every summary assertion below.
    """
    missing = tmp_path / "missing-manifest.json"
    monkeypatch.setenv("CAMERA_MANIFEST_PATH", str(missing))


def _seed_analysis(store: JsonStore, camera_id: str = "cam1") -> None:
    store.save_json(
        f"analyses/{camera_id}/001.json",
        {
            "camera_id": camera_id,
            "captured_at": "2026-06-24T08:00:00Z",
            "label": "heavy",
            "details": {
                "density": "heavy",
                "vehicle_count": 42,
                "mean_confidence": 0.5,
                "active_tracks": 10,
                "scene": "day",
                "flow_rate_vph": {"northbound": 5, "southbound": 6, "total": 11},
                "per_frame": [{"frame_idx": 0, "vehicle_count": 42}],
                "capture_result": {
                    "name": "Outer Harbour",
                    "district": "澳門區",
                    "sub_district": "外港",
                    "stream_url": "https://example/stream.m3u8",
                    "latitude": 22.195,
                    "longitude": 113.558,
                },
            },
        },
    )


def test_api_routes_import_and_list_cameras(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)

    module = reload(routes)
    cameras = module.list_cameras(store=store)

    assert [camera["camera_id"] for camera in cameras] == ["cam1"]
    assert cameras[0]["latest_density"] == "heavy"
    assert cameras[0]["map_position"]["source"] == "coordinates"
    assert cameras[0]["map_position"]["latitude"] == 22.195


def test_list_cameras_exposes_flow_split_and_coordinates(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)

    module = reload(routes)
    cameras = module.list_cameras(store=store)

    assert cameras[0]["latest_flow_split"] == {"northbound": 5, "southbound": 6, "total": 11}
    assert cameras[0]["latitude"] == 22.195
    assert cameras[0]["longitude"] == 113.558


def test_get_camera_returns_latest_detail(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)

    module = reload(routes)
    detail = module.get_camera("cam1", store=store)

    assert detail["camera_id"] == "cam1"
    assert detail["density"] == "heavy"
    assert detail["vehicle_count"] == 42
    assert detail["stream_url"] == "https://example/stream.m3u8"
    assert detail["flow_rate_vph"]["total"] == 11
    assert detail["per_frame"][0]["vehicle_count"] == 42
    assert detail["map_position"]["source"] == "coordinates"


def test_get_camera_unknown_raises_404(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)

    module = reload(routes)
    with pytest.raises(HTTPException) as excinfo:
        module.get_camera("nope", store=store)

    assert excinfo.value.status_code == 404


def test_get_camera_history_returns_recent_records(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)
    store.save_json(
        "analyses/cam1/002.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T09:00:00Z",
            "label": "blocked",
            "details": {"density": "blocked", "vehicle_count": 55},
        },
    )

    module = reload(routes)
    history = module.get_camera_history("cam1", store=store)

    assert [entry["captured_at"] for entry in history] == [
        "2026-06-24T08:00:00Z",
        "2026-06-24T09:00:00Z",
    ]
    assert history[-1]["density"] == "blocked"
