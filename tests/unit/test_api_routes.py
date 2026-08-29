import json
from datetime import datetime, timezone
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
    monkeypatch.setenv("CAMERA_COORDS_PATH", str(tmp_path / "missing-coordinates.json"))
    monkeypatch.setenv(
        "CAMERA_SPEED_CALIBRATION_PATH",
        str(tmp_path / "missing-speed-calibration.json"),
    )


def _seed_analysis(
    store: JsonStore,
    camera_id: str = "cam1",
    *,
    latitude: float = 22.195,
    longitude: float = 113.558,
    captured_at: str = "2026-06-24T08:00:00Z",
    density: str = "heavy",
    congestion_score: float = 72.0,
) -> None:
    store.save_json(
        f"analyses/{camera_id}/001.json",
        {
            "camera_id": camera_id,
            "captured_at": captured_at,
            "label": density,
            "details": {
                "density": density,
                "vehicle_count": 42,
                "congestion_score": congestion_score,
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
                    "latitude": latitude,
                    "longitude": longitude,
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


def test_traffic_reliability_distinguishes_live_stale_and_calibrated() -> None:
    now = datetime(2026, 8, 28, 14, 30, tzinfo=timezone.utc)
    uncalibrated = {"is_calibrated": False}
    calibrated = {"is_calibrated": True}

    provisional = routes._traffic_reliability(
        "2026-08-28T14:15:00Z",
        42.0,
        uncalibrated,
        0.8,
        now=now,
    )
    reliable = routes._traffic_reliability(
        "2026-08-28T14:10:00Z",
        42.0,
        calibrated,
        0.8,
        now=now,
    )
    stale = routes._traffic_reliability(
        "2026-08-28T14:09:00Z",
        42.0,
        calibrated,
        0.8,
        now=now,
    )

    assert provisional["level"] == "provisional"
    assert provisional["is_live"] is True
    assert reliable["level"] == "reliable"
    assert reliable["age_minutes"] == 20
    assert stale["level"] == "stale"
    assert stale["is_live"] is False


def test_traffic_reliability_marks_missing_score_unavailable() -> None:
    status = routes._traffic_reliability(None, None, {"is_calibrated": False})

    assert status["level"] == "unavailable"
    assert status["is_live"] is False
    assert status["age_minutes"] is None


def test_list_cameras_only_loads_latest_record_per_camera(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(
        store,
        captured_at="2026-06-24T08:00:00Z",
        density="heavy",
        congestion_score=72.0,
    )
    store.save_json(
        "analyses/cam1/20260624T090000Z_9.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T09:00:00Z",
            "label": "blocked",
            "details": {
                "density": "blocked",
                "congestion_score": 90.0,
                "capture_result": {"name": "Outer Harbour"},
            },
        },
    )
    store.save_json(
        "analyses/cam1/20260624T090000Z_10.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T09:00:00Z",
            "label": "light",
            "details": {
                "density": "light",
                "congestion_score": 12.0,
                "capture_result": {"name": "Outer Harbour"},
            },
        },
    )

    module = reload(routes)
    cameras = module.list_cameras(store=store)

    assert len(cameras) == 1
    assert cameras[0]["latest_captured_at"] == "2026-06-24T09:00:00Z"
    assert cameras[0]["latest_density"] == "light"
    assert cameras[0]["latest_congestion_score"] == 12.0


def test_default_overview_refreshes_calibration_in_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)
    module = reload(routes)
    started: list[tuple] = []

    class _FakeThread:
        def __init__(self, *, target, args, name, daemon):
            started.append((target, args, name, daemon))

        def start(self) -> None:
            return None

    monkeypatch.setattr(module.threading, "Thread", _FakeThread)
    summary = module._overview_calibration_summary(store, wait_for_refresh=False)

    assert summary["refreshing"] is True
    assert len(started) == 1
    assert started[0][2] == "trafficcam-calibration-summary"
    assert started[0][3] is True


def test_list_cameras_exposes_flow_split_and_coordinates(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "camera_speed_calibration.json").write_text(
        json.dumps({"cameras": {"cam1": {"freeflow_px_per_frame": 12.5, "sample_count": 7, "offpeak_hours": "02-05"}}}),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as local_patch:
        local_patch.chdir(tmp_path)
        module = reload(routes)
        cameras = module.list_cameras(store=store)

        assert cameras[0]["latest_flow_split"] == {"northbound": 5, "southbound": 6, "total": 11}
        assert cameras[0]["latitude"] == 22.195
        assert cameras[0]["longitude"] == 113.558
        assert cameras[0]["calibration"] == {
            "status": "calibrated",
            "is_calibrated": True,
            "freeflow_px_per_frame": 12.5,
            "sample_count": 7,
            "offpeak_hours": "02-05",
        }


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
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "camera_speed_calibration.json").write_text(
        json.dumps({"cameras": {"cam1": {"freeflow_px_per_frame": 12.5, "sample_count": 7, "offpeak_hours": "02-05"}}}),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as local_patch:
        local_patch.chdir(tmp_path)
        module = reload(routes)
        detail = module.get_camera("cam1", store=store)

        assert detail["camera_id"] == "cam1"
        assert detail["density"] == "heavy"
        assert detail["vehicle_count"] == 42
        assert detail["stream_url"] == "https://example/stream.m3u8"
        assert detail["flow_rate_vph"]["total"] == 11
        assert detail["per_frame"][0]["vehicle_count"] == 42
        assert detail["map_position"]["source"] == "coordinates"
        assert detail["calibration"] == {
            "status": "calibrated",
            "is_calibrated": True,
            "freeflow_px_per_frame": 12.5,
            "sample_count": 7,
            "offpeak_hours": "02-05",
        }


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
    assert detail["calibration"] == {
        "status": "uncalibrated",
        "is_calibrated": False,
        "freeflow_px_per_frame": None,
        "sample_count": None,
        "offpeak_hours": None,
    }


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


def test_get_overview_includes_corridor_segments(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(
        store,
        "cam1",
        latitude=22.195,
        longitude=113.558,
        density="heavy",
        congestion_score=72.0,
    )
    _seed_analysis(
        store,
        "cam2",
        latitude=22.1965,
        longitude=113.5605,
        density="moderate",
        congestion_score=46.0,
    )
    corridor_path = tmp_path / "camera_corridors.json"
    corridor_path.write_text(
        json.dumps({"corridors": [{"corridor_id": "outer-harbour", "name": "Outer Harbour", "camera_ids": ["cam1", "cam2"]}]}),
        encoding="utf-8",
    )

    with pytest.MonkeyPatch.context() as local_patch:
        local_patch.chdir(tmp_path)
        local_patch.setenv("CAMERA_CORRIDORS_PATH", str(corridor_path))
        module = reload(routes)
        overview = module.get_overview(store=store)

    assert overview["camera_count"] == 2
    assert len(overview["corridor_segments"]) == 1
    segment = overview["corridor_segments"][0]
    assert segment["camera_ids"] == ["cam1", "cam2"]
    assert segment["corridor_id"] == "outer-harbour"
    assert segment["name"] == "Outer Harbour"
    assert segment["district"] == "澳門區"
    assert segment["sub_district"] == "外港"
    assert segment["density"] == "heavy"
    assert segment["average_score"] == pytest.approx(59.0)
    assert segment["is_approximate"] is False


def test_get_overview_omits_unconfigured_corridors(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store, "cam1")
    module = reload(routes)
    overview = module.get_overview(store=store)
    assert overview["corridor_segments"] == []
    calibration = overview["calibration_summary"]
    assert calibration["configured"] == 0
    assert calibration["missing"] == 1
    assert calibration["missing_motion_history"] == 1
    assert calibration["next_ready_camera_ids"] == []
    assert overview["live_camera_count"] == 0
    assert overview["live_average_score"] is None
    assert overview["reliability_counts"]["stale"] == 1


def test_get_overview_omits_disabled_corridors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = JsonStore(tmp_path)
    _seed_analysis(store, "cam1")
    _seed_analysis(store, "cam2", latitude=22.196, longitude=113.56)
    corridor_path = tmp_path / "camera_corridors.json"
    corridor_path.write_text(
        json.dumps(
            {
                "corridors": [
                    {"corridor_id": "disabled", "camera_ids": ["cam1", "cam2"], "enabled": False}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAMERA_CORRIDORS_PATH", str(corridor_path))

    module = reload(routes)
    overview = module.get_overview(store=store)

    assert overview["corridor_segments"] == []


def test_get_overview_reports_calibration_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cameras": [
                    {"cam_id": "49", "name": "Cam 49", "district": "澳門區", "sub_district": "外港"},
                    {"cam_id": "50", "name": "Cam 50", "district": "澳門區", "sub_district": "外港"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAMERA_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv(
        "CAMERA_SPEED_CALIBRATION_PATH",
        str(tmp_path / "camera_speed_calibration.json"),
    )
    store = JsonStore(tmp_path)

    for index in range(5):
        store.save_json(
            f"analyses/50/{index:03d}.json",
            {
                "camera_id": "50",
                # 18:xx UTC is 02:xx the following day in Macau.
                "captured_at": f"2026-06-23T18:0{index}:00Z",
                "label": "moderate",
                "details": {
                    "density": "moderate",
                    "congestion_score": 40.0,
                    "median_speed_px_per_frame": 10.0 + index,
                    "capture_result": {
                        "name": "Cam 50",
                        "district": "澳門區",
                        "sub_district": "外港",
                        "latitude": 22.19,
                        "longitude": 113.55,
                    },
                },
            },
        )

    with pytest.MonkeyPatch.context() as local_patch:
        local_patch.chdir(tmp_path)
        module = reload(routes)
        overview = module.get_overview(store=store)

    calibration = overview["calibration_summary"]
    assert calibration["configured"] == 0
    assert calibration["ready"] == 1
    assert calibration["missing"] == 2
    assert calibration["next_ready_camera_ids"] == ["50"]


def test_get_overview_reports_human_calibration_tasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cameras": [
                    {"cam_id": "49", "name": "Cam 49", "district": "澳門區"},
                    {"cam_id": "70", "name": "Cam 70", "district": "澳門區"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    coords_path = tmp_path / "camera_coordinates.json"
    coords_path.write_text(
        json.dumps({"cameras": {"49": {"latitude": 22.19, "longitude": 113.54}}}),
        encoding="utf-8",
    )
    rois_path = tmp_path / "camera_rois.json"
    rois_path.write_text(json.dumps({"49": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]}), encoding="utf-8")
    flow_path = tmp_path / "camera_flow_lines.json"
    flow_path.write_text(json.dumps({"49": {"start": [0.0, 0.5], "end": [1.0, 0.5]}}), encoding="utf-8")
    corridor_path = tmp_path / "camera_corridors.json"
    corridor_path.write_text(
        json.dumps(
            {
                "corridors": [
                    {"corridor_id": "named", "name": "Guia Tunnel", "camera_ids": ["69", "70"], "enabled": False}
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CAMERA_MANIFEST_PATH", str(manifest_path))
    monkeypatch.setenv("CAMERA_COORDS_PATH", str(coords_path))
    monkeypatch.setenv("ROI_CONFIG_PATH", str(rois_path))
    monkeypatch.setenv("FLOW_LINE_CONFIG_PATH", str(flow_path))
    monkeypatch.setenv("CAMERA_CORRIDORS_PATH", str(corridor_path))
    store = JsonStore(tmp_path)
    _seed_analysis(store, "49", latitude=22.19, longitude=113.54)

    module = reload(routes)
    overview = module.get_overview(store=store)
    human = overview["human_calibration"]

    assert human["human_required"] is True
    assert human["gaps"]["missing_coordinates"] == 1
    assert human["gaps"]["missing_rois"] == 1
    assert human["gaps"]["missing_flow_lines"] == 1
    assert human["gaps"]["disabled_corridor_names"] == ["Guia Tunnel"]
    tasks = {task["id"]: task for task in human["tasks"]}
    assert tasks["place-cameras"]["owner"] == "human"
    assert tasks["place-cameras"]["remaining"] == 1
    assert tasks["verify-corridors"]["remaining"] == 1
    assert tasks["run-calibrate-freeflow"]["owner"] == "automated"
