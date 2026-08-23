import json
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


def test_list_cameras_includes_manifest_only_cameras(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cameras": [
                    {
                        "cam_id": "cam59",
                        "name": "New Discovery",
                        "district": "澳門區",
                        "sub_district": "外港",
                        "detail_url": "https://example/detail",
                        "stream_urls": ["https://example/stream.m3u8"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAMERA_MANIFEST_PATH", str(manifest_path))
    store = JsonStore(tmp_path)

    module = reload(routes)
    cameras = module.list_cameras(store=store)

    assert [camera["camera_id"] for camera in cameras] == ["cam59"]
    assert cameras[0]["name"] == "New Discovery"
    assert cameras[0]["latest_density"] == "unknown"
    assert cameras[0]["map_position"]["source"] == "approximate"
    assert cameras[0]["latitude"] is not None
    assert cameras[0]["longitude"] is not None


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


def test_get_camera_returns_manifest_only_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cameras": [
                    {
                        "cam_id": "59",
                        "name": "New Discovery",
                        "district": "澳門區",
                        "sub_district": "外港",
                        "detail_url": "https://example/detail",
                        "stream_urls": ["https://example/stream.m3u8"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAMERA_MANIFEST_PATH", str(manifest_path))
    store = JsonStore(tmp_path)

    module = reload(routes)
    detail = module.get_camera("59", store=store)

    assert detail["camera_id"] == "59"
    assert detail["name"] == "New Discovery"
    assert detail["density"] == "unknown"
    assert detail["stream_url"] == "https://example/stream.m3u8"
    assert detail["latest_image_url"] is None
    assert detail["per_frame"] == []
    assert detail["map_position"]["source"] == "approximate"
    assert detail["map_position"]["latitude"] is not None
    assert detail["map_position"]["longitude"] is not None


def test_get_camera_cache_busts_frame_urls(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    store.save_json(
        "analyses/cam1/001.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T08:00:00Z",
            "label": "heavy",
            "details": {
                "density": "heavy",
                "vehicle_count": 42,
                "per_frame": [{"frame_idx": 0, "image_path": "output/cam1/frame_001.jpg"}],
                "capture_result": {"name": "Outer Harbour", "district": "澳門區", "sub_district": "外港", "stream_url": "https://example/stream.m3u8"},
            },
        },
    )

    module = reload(routes)
    detail = module.get_camera("cam1", store=store)

    assert detail["latest_image_url"].startswith("/output/cam1/frame_001.jpg?v=")


def test_data_dir_signature_changes_when_analysis_files_change(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    module = reload(routes)
    before = module._data_dir_signature(store)

    store.save_json(
        "analyses/cam1/001.json",
        {"camera_id": "cam1", "captured_at": "2026-06-24T08:00:00Z"},
    )
    after = module._data_dir_signature(store)

    assert before != after


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


def test_update_camera_position_persists_coordinates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_COORDS_PATH", str(tmp_path / "camera_coordinates.json"))

    module = reload(routes)
    result = module.update_camera_position(
        "cam9",
        {"latitude": 22.1905, "longitude": 113.5505},
    )

    assert result["camera_id"] == "cam9"
    assert result["latitude"] == 22.1905
    assert result["longitude"] == 113.5505
    payload = json.loads((tmp_path / "camera_coordinates.json").read_text(encoding="utf-8"))
    assert payload["cameras"]["cam9"]["latitude"] == 22.1905
    assert payload["cameras"]["cam9"]["longitude"] == 113.5505
