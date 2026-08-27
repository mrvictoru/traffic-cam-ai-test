from __future__ import annotations

import json

import trafficcam.web.map_page as map_page


def test_render_map_page_embeds_corridor_and_calibration_payload(monkeypatch) -> None:
    cameras = [
        {
            "camera_id": "51",
            "name": "Friendship Bridge",
            "latest_density": "moderate",
            "latest_congestion_score": 42.0,
            "map_position": {
                "source": "coordinates",
                "latitude": 22.1992,
                "longitude": 113.5628,
            },
        }
    ]
    overview = {
        "camera_count": 1,
        "density_counts": {"light": 0, "moderate": 1, "heavy": 0, "blocked": 0, "unknown": 0},
        "average_score": 42.0,
        "corridor_segments": [
            {
                "segment_id": "friendship-bridge:1",
                "corridor_id": "friendship-bridge",
                "name": "Friendship Bridge",
                "camera_ids": ["51", "52"],
                "start": {"latitude": 22.1992, "longitude": 113.5628},
                "end": {"latitude": 22.1566, "longitude": 113.5839},
                "average_score": 42.0,
                "density": "moderate",
                "is_approximate": False,
            }
        ],
        "calibration_summary": {
            "configured": 1,
            "ready": 2,
            "insufficient_history": 3,
            "next_ready_camera_ids": ["51", "52"],
        },
    }
    monkeypatch.setattr(map_page, "build_camera_summaries", lambda store=None: cameras)
    monkeypatch.setattr(map_page, "get_overview", lambda store=None: overview)

    html = map_page.render_map_page()

    assert "L.polyline" in html
    assert "CORRIDOR_SEGMENTS" in html
    assert "Calibrated" in html
    assert "Need history" in html
    assert "friendship-bridge:1" in html
    assert '"configured": 1' in html
    assert '"next_ready_camera_ids": ["51", "52"]' in html
    assert "__PAYLOAD_JSON__" not in html
    assert "__DENSITY_COLORS__" not in html


def test_payload_falls_back_when_overview_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(map_page, "build_camera_summaries", lambda store=None: [])

    def fail_overview(store=None):
        raise OSError("overview unavailable")

    monkeypatch.setattr(map_page, "get_overview", fail_overview)

    payload = json.loads(map_page._payload(None))

    assert payload == {"cameras": [], "overview": {}}
