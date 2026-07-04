from pathlib import Path

from trafficcam.vision.roi import filter_detections_to_roi, load_camera_rois, point_in_polygon


def test_point_in_polygon_basic_square() -> None:
    polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert point_in_polygon(0.5, 0.5, polygon) is True
    assert point_in_polygon(1.2, 0.5, polygon) is False


def test_filter_detections_to_roi_keeps_only_centers_inside() -> None:
    polygon = [[0.0, 0.0], [0.6, 0.0], [0.6, 1.0], [0.0, 1.0]]
    detections = [
        {
            "label": "car",
            "confidence": 0.9,
            "box": {"xmin": 10.0, "ymin": 10.0, "xmax": 30.0, "ymax": 30.0},
        },
        {
            "label": "car",
            "confidence": 0.9,
            "box": {"xmin": 80.0, "ymin": 10.0, "xmax": 100.0, "ymax": 30.0},
        },
    ]

    filtered = filter_detections_to_roi(detections, polygon, image_width=100, image_height=100)
    assert len(filtered) == 1
    assert filtered[0]["box"]["xmin"] == 10.0


def test_load_camera_rois_reads_valid_json(tmp_path: Path) -> None:
    config_path = tmp_path / "camera_rois.json"
    config_path.write_text(
        '{"49": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.9], [0.1, 0.9]], "bad": [1, 2, 3]}',
        encoding="utf-8",
    )

    rois = load_camera_rois(config_path)
    assert "49" in rois
    assert "bad" not in rois
