"""Helpers for camera ROI loading and detection filtering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import supervision as sv

    _SUPERVISION_AVAILABLE = True
except Exception:  # pragma: no cover
    _SUPERVISION_AVAILABLE = False


def load_camera_rois(config_path: str | Path) -> dict[str, list[list[float]]]:
    """Load camera ROI polygons from a JSON file.

    Expected shape:
    {
      "49": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.95], [0.1, 0.95]],
      "51": ...
    }
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return {}

    normalized: dict[str, list[list[float]]] = {}
    for camera_id, polygon in parsed.items():
        if not isinstance(camera_id, str) or not isinstance(polygon, list):
            continue
        points: list[list[float]] = []
        for point in polygon:
            if not isinstance(point, list) or len(point) != 2:
                continue
            try:
                x = float(point[0])
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            points.append([x, y])
        if len(points) >= 3:
            normalized[camera_id] = points
    return normalized


def load_camera_flow_lines(
    config_path: str | Path,
) -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
    """Load normalized per-camera counting lines from JSON.

    Expected shape:
    {
      "51": {"start": [0.0, 0.52], "end": [1.0, 0.52]}
    }
    """
    path = Path(config_path)
    if not path.exists():
        return {}

    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        return {}

    normalized: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
    for camera_id, line in parsed.items():
        if not isinstance(camera_id, str) or not isinstance(line, dict):
            continue
        start = line.get("start")
        end = line.get("end")
        if not isinstance(start, list) or not isinstance(end, list):
            continue
        if len(start) != 2 or len(end) != 2:
            continue
        try:
            normalized[camera_id] = (
                (float(start[0]), float(start[1])),
                (float(end[0]), float(end[1])),
            )
        except (TypeError, ValueError):
            continue
    return normalized


def image_size(image_path: str | Path) -> tuple[int, int]:
    """Return image width and height."""
    with Image.open(image_path) as image:
        return image.width, image.height


def line_to_pixels(
    line_norm: tuple[tuple[float, float], tuple[float, float]],
    image_width: int,
    image_height: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Convert a normalized line definition into image-space points."""
    start, end = line_norm
    return (
        (start[0] * float(image_width), start[1] * float(image_height)),
        (end[0] * float(image_width), end[1] * float(image_height)),
    )


def _polygon_to_pixels(
    polygon_norm: list[list[float]],
    image_width: int,
    image_height: int,
) -> np.ndarray:
    return np.array(
        [
            [point[0] * float(image_width), point[1] * float(image_height)]
            for point in polygon_norm
        ],
        dtype=np.int32,
    )


def _filter_detections_with_supervision(
    detections: list[dict[str, Any]],
    polygon_norm: list[list[float]],
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    if not detections:
        return []

    xyxy = np.array(
        [
            [
                float(det.get("box", {}).get("xmin", 0.0)),
                float(det.get("box", {}).get("ymin", 0.0)),
                float(det.get("box", {}).get("xmax", 0.0)),
                float(det.get("box", {}).get("ymax", 0.0)),
            ]
            for det in detections
        ],
        dtype=np.float32,
    )
    confidence = np.array(
        [float(det.get("confidence", 0.0)) for det in detections],
        dtype=np.float32,
    )
    zone = sv.PolygonZone(polygon=_polygon_to_pixels(polygon_norm, image_width, image_height))
    mask = zone.trigger(sv.Detections(xyxy=xyxy, confidence=confidence))
    return [det for det, keep in zip(detections, mask.tolist()) if keep]


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point in polygon test."""
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y)
        if intersects:
            x_edge = (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
            if x < x_edge:
                inside = not inside
        j = i
    return inside


def filter_detections_to_roi(
    detections: list[dict[str, Any]],
    polygon_norm: list[list[float]],
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    """Keep only detections whose box center is inside the normalized ROI polygon."""
    if not polygon_norm:
        return detections
    if _SUPERVISION_AVAILABLE:
        return _filter_detections_with_supervision(
            detections,
            polygon_norm,
            image_width,
            image_height,
        )

    filtered: list[dict[str, Any]] = []
    for detection in detections:
        box = detection.get("box", {})
        xmin = float(box.get("xmin", 0.0))
        ymin = float(box.get("ymin", 0.0))
        xmax = float(box.get("xmax", 0.0))
        ymax = float(box.get("ymax", 0.0))
        cx_norm = ((xmin + xmax) / 2.0) / float(image_width or 1)
        cy_norm = ((ymin + ymax) / 2.0) / float(image_height or 1)
        if point_in_polygon(cx_norm, cy_norm, polygon_norm):
            filtered.append(detection)

    return filtered
