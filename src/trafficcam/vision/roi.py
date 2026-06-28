"""Helpers for camera ROI loading and detection filtering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image


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


def image_size(image_path: str | Path) -> tuple[int, int]:
    """Return image width and height."""
    with Image.open(image_path) as image:
        return image.width, image.height


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
