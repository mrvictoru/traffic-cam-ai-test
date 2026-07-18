from importlib import reload
from pathlib import Path

import trafficcam.api.routes as routes
from trafficcam.storage.json_store import JsonStore


def test_api_routes_import_and_list_cameras(tmp_path: Path) -> None:
    store = JsonStore(tmp_path)
    store.save_json(
        "analyses/cam1/001.json",
        {
            "camera_id": "cam1",
            "captured_at": "2026-06-24T08:00:00Z",
            "label": "heavy",
            "details": {
                "density": "heavy",
                "capture_result": {
                    "name": "Outer Harbour",
                    "district": "澳門區",
                    "sub_district": "外港",
                    "latitude": 22.195,
                    "longitude": 113.558,
                },
            },
        },
    )

    module = reload(routes)
    cameras = module.list_cameras(store=store)

    assert [camera["camera_id"] for camera in cameras] == ["cam1"]
    assert cameras[0]["latest_density"] == "heavy"
    assert cameras[0]["map_position"]["source"] == "coordinates"
    assert cameras[0]["map_position"]["latitude"] == 22.195
