"""Route definitions for the API scaffold."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter

from trafficcam.storage.json_store import JsonStore

router = APIRouter()

_HASH_KEY_SEPARATOR = "::"
_HASH_BYTE_MAX = 255.0
_HASH_CENTER_OFFSET = 0.5
_APPROXIMATE_JITTER_RANGE = 14.0
_DISTRICT_MAP_ANCHORS: dict[str, tuple[float, float]] = {
    "澳門區": (34.0, 40.0),
    "路氹區": (63.0, 72.0),
    "跨海大橋": (52.0, 48.0),
    "新城A區": (58.0, 56.0),
    "口岸": (76.0, 38.0),
    "unknown": (50.0, 50.0),
}
_MACAU_MAP_BOUNDS = {
    "lat_min": 22.10,
    "lat_max": 22.24,
    "lon_min": 113.52,
    "lon_max": 113.62,
}
_DENSITY_PRIORITY = {
    "blocked": 4,
    "heavy": 3,
    "moderate": 2,
    "light": 1,
    "unknown": 0,
}


def _load_analyses(store: JsonStore) -> list[dict[str, Any]]:
    return [
        store.load_json(path)
        for path in store.list_records(prefix="analyses/")
        if path.endswith(".json")
    ]


def _coerce_coordinate(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iter_coordinate_payloads(*payloads: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        results.append(payload)
        for key in ("location", "coordinates", "coordinate", "geo", "map_position", "metadata"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                results.append(nested)
    return results


def _first_coordinate(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _coerce_coordinate(payload.get(key))
        if value is not None:
            return value
    return None


def _extract_coordinates(analysis: dict[str, Any], capture_result: dict[str, Any]) -> tuple[float | None, float | None]:
    for payload in _iter_coordinate_payloads(analysis, analysis.get("details"), capture_result):
        latitude = _first_coordinate(payload, "lat", "latitude")
        longitude = _first_coordinate(payload, "lon", "lng", "longitude")
        if latitude is not None and longitude is not None:
            return latitude, longitude
    return None, None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _map_position_from_coordinates(latitude: float, longitude: float) -> dict[str, Any]:
    lat_min = _MACAU_MAP_BOUNDS["lat_min"]
    lat_max = _MACAU_MAP_BOUNDS["lat_max"]
    lon_min = _MACAU_MAP_BOUNDS["lon_min"]
    lon_max = _MACAU_MAP_BOUNDS["lon_max"]
    x_percent = ((longitude - lon_min) / (lon_max - lon_min)) * 100.0
    y_percent = (1.0 - ((latitude - lat_min) / (lat_max - lat_min))) * 100.0
    return {
        "x_percent": round(_clamp(x_percent, 4.0, 96.0), 1),
        "y_percent": round(_clamp(y_percent, 4.0, 96.0), 1),
        "source": "coordinates",
        "latitude": latitude,
        "longitude": longitude,
    }


def _approximate_map_position(camera_id: str, district: str | None, sub_district: str | None) -> dict[str, Any]:
    anchor_x, anchor_y = _DISTRICT_MAP_ANCHORS.get(district or "", _DISTRICT_MAP_ANCHORS["unknown"])
    district_value = district or ""
    sub_district_value = sub_district or ""
    digest = hashlib.sha256(
        f"{district_value}{_HASH_KEY_SEPARATOR}{sub_district_value}{_HASH_KEY_SEPARATOR}{camera_id}".encode("utf-8")
    ).digest()
    x_jitter = ((digest[0] / _HASH_BYTE_MAX) - _HASH_CENTER_OFFSET) * _APPROXIMATE_JITTER_RANGE
    y_jitter = ((digest[1] / _HASH_BYTE_MAX) - _HASH_CENTER_OFFSET) * _APPROXIMATE_JITTER_RANGE
    return {
        "x_percent": round(_clamp(anchor_x + x_jitter, 6.0, 94.0), 1),
        "y_percent": round(_clamp(anchor_y + y_jitter, 6.0, 94.0), 1),
        "source": "approximate",
    }


def _build_map_position(
    camera_id: str,
    district: str | None,
    sub_district: str | None,
    analysis: dict[str, Any],
    capture_result: dict[str, Any],
) -> dict[str, Any]:
    latitude, longitude = _extract_coordinates(analysis, capture_result)
    if latitude is not None and longitude is not None:
        return _map_position_from_coordinates(latitude, longitude)
    return _approximate_map_position(camera_id, district, sub_district)


def build_camera_summaries(store: Any = None) -> list[dict[str, Any]]:
    """Return camera summaries enriched with congestion and map-position metadata."""
    if store is None:
        store = JsonStore("data")

    analyses = _load_analyses(store)
    grouped: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        camera_id = analysis.get("camera_id") or "unknown"
        details = analysis.get("details") or {}
        capture_result = details.get("capture_result") or {}
        density = details.get("density") or analysis.get("label") or "unknown"
        captured_at = analysis.get("captured_at")
        total_flow = details.get("flow_rate_vph") or {}
        existing = grouped.setdefault(
            camera_id,
            {
                "camera_id": camera_id,
                "name": capture_result.get("name"),
                "district": capture_result.get("district"),
                "sub_district": capture_result.get("sub_district"),
                "latest_density": None,
                "latest_captured_at": None,
                "latest_label": None,
                "latest_flow_total": None,
                "density_rank": _DENSITY_PRIORITY["unknown"],
                "map_position": _approximate_map_position(
                    camera_id,
                    capture_result.get("district"),
                    capture_result.get("sub_district"),
                ),
            },
        )
        if not existing.get("name"):
            existing["name"] = capture_result.get("name")
        if not existing.get("district"):
            existing["district"] = capture_result.get("district")
        if not existing.get("sub_district"):
            existing["sub_district"] = capture_result.get("sub_district")
        if existing["latest_captured_at"] is None or (captured_at or "") >= (existing["latest_captured_at"] or ""):
            existing["latest_density"] = density
            existing["latest_captured_at"] = captured_at
            existing["latest_label"] = analysis.get("label")
            existing["latest_flow_total"] = total_flow.get("total")
            existing["density_rank"] = _DENSITY_PRIORITY.get(str(density).lower(), _DENSITY_PRIORITY["unknown"])
            existing["map_position"] = _build_map_position(
                camera_id,
                existing.get("district"),
                existing.get("sub_district"),
                analysis,
                capture_result,
            )

    return sorted(grouped.values(), key=lambda item: item["camera_id"])


@router.get("/cameras")
def list_cameras(store: Any = None) -> list[dict[str, Any]]:
    """Return a lightweight summary for each camera seen in persisted analyses."""
    return build_camera_summaries(store=store)
