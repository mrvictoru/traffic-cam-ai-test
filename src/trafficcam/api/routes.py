"""Route definitions for the API scaffold."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from trafficcam.storage.json_store import JsonStore

router = APIRouter()

# Optional hand-seeded camera coordinates (cam_id -> lat/lon) used to place
# markers on the real map. Path is configurable for tests and deployments.
_COORDS_CONFIG_PATH = Path(os.getenv("CAMERA_COORDS_PATH", "config/camera_coordinates.json"))


def _load_camera_coordinates(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load hand-seeded camera coordinates keyed by camera id.

    Returns an empty mapping when the file is missing or invalid so the
    dashboard can fall back to approximate placement.
    """
    target = path or _COORDS_CONFIG_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cameras = payload.get("cameras")
    if not isinstance(cameras, dict):
        return {}
    results: dict[str, dict[str, Any]] = {}
    for cam_id, entry in cameras.items():
        if not isinstance(entry, dict):
            continue
        lat = _coerce_coordinate(entry.get("latitude"))
        lon = _coerce_coordinate(entry.get("longitude"))
        if lat is None or lon is None:
            continue
        record: dict[str, Any] = {"latitude": lat, "longitude": lon}
        if entry.get("name"):
            record["name"] = entry.get("name")
        if entry.get("bearing") is not None:
            bearing = _coerce_coordinate(entry.get("bearing"))
            if bearing is not None:
                record["bearing"] = bearing
        results[str(cam_id)] = record
    return results

# Hash inputs are normalized and separated so approximate positions remain stable
# across reloads while changing predictably when location metadata changes.
_HASH_KEY_SEPARATOR = "::"
# SHA-256 digest bytes are scaled from 0..255 into a centered jitter offset.
_HASH_BYTE_MAX = 255.0
_HASH_CENTER_OFFSET = 0.5
# Keep fallback markers near their district anchor while still avoiding overlap.
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
    """Extract the first usable latitude/longitude pair from stored analysis payloads.

    Search order favors the newest analysis record, then nested analysis details,
    then capture metadata. Each payload accepts common coordinate aliases so the
    dashboard can use real camera positions whenever they become available.
    """
    for payload in _iter_coordinate_payloads(analysis, analysis.get("details"), capture_result):
        latitude = _first_coordinate(payload, "lat", "latitude")
        longitude = _first_coordinate(payload, "lon", "lng", "longitude")
        if latitude is not None and longitude is not None:
            return latitude, longitude
    return None, None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _map_position_from_coordinates(latitude: float, longitude: float) -> dict[str, Any]:
    """Project Macau lat/lon coordinates into dashboard percentage positions.

    The bounds cover the Macau area used by this first-pass dashboard. Values are
    normalized into 0-100 percentages and then clamped to keep markers visible
    inside the rendered map surface.
    """
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
    """Build a deterministic fallback map position when camera coordinates are missing.

    Each district maps to a coarse anchor on the dashboard. A small SHA-256 based
    jitter derived from district, sub-district, and camera id spreads markers so
    cameras in the same area remain stable across renders without overlapping.
    """
    anchor_x, anchor_y = _DISTRICT_MAP_ANCHORS.get(district or "", _DISTRICT_MAP_ANCHORS["unknown"])
    district_value = district or ""
    sub_district_value = sub_district or ""
    digest = hashlib.sha256(
        _HASH_KEY_SEPARATOR.join([district_value, sub_district_value, camera_id]).encode("utf-8")
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
    coordinates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a camera's map position.

    Priority: hand-seeded config coordinates, then coordinates embedded in the
    analysis payloads, then a deterministic district-based approximation.
    """
    config_entry = (coordinates or {}).get(str(camera_id))
    if config_entry is not None:
        position = _map_position_from_coordinates(config_entry["latitude"], config_entry["longitude"])
        if config_entry.get("bearing") is not None:
            position["bearing"] = config_entry["bearing"]
        return position
    latitude, longitude = _extract_coordinates(analysis, capture_result)
    if latitude is not None and longitude is not None:
        return _map_position_from_coordinates(latitude, longitude)
    return _approximate_map_position(camera_id, district, sub_district)


def _resolve_density(analysis: dict[str, Any], details: dict[str, Any]) -> str:
    """Return the best available congestion label for an analysis record."""
    return str(details.get("density") or analysis.get("label") or "unknown")


def build_camera_summaries(store: Any = None) -> list[dict[str, Any]]:
    """Return camera summaries enriched with congestion and map-position metadata."""
    if store is None:
        store = JsonStore("data")

    coordinates = _load_camera_coordinates()
    analyses = _load_analyses(store)
    grouped: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        camera_id = analysis.get("camera_id") or "unknown"
        details = analysis.get("details") or {}
        capture_result = details.get("capture_result") or {}
        density = _resolve_density(analysis, details)
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
                "latest_flow_split": None,
                "latitude": None,
                "longitude": None,
                "density_rank": _DENSITY_PRIORITY["unknown"],
                "map_position": None,
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
            existing["latest_flow_split"] = total_flow if total_flow else None
            existing["density_rank"] = _DENSITY_PRIORITY.get(str(density).lower(), _DENSITY_PRIORITY["unknown"])
            existing["map_position"] = _build_map_position(
                camera_id,
                existing.get("district"),
                existing.get("sub_district"),
                analysis,
                capture_result,
                coordinates,
            )
        if existing.get("latitude") is None and existing.get("map_position"):
            position = existing["map_position"]
            if position.get("latitude") is not None and position.get("longitude") is not None:
                existing["latitude"] = position.get("latitude")
                existing["longitude"] = position.get("longitude")

    return sorted(grouped.values(), key=lambda item: item["camera_id"])


def _latest_analysis_for_camera(store: Any, camera_id: str) -> dict[str, Any] | None:
    """Return the newest persisted analysis record for a camera, or None."""
    analyses = [
        record
        for record in _load_analyses(store)
        if str(record.get("camera_id")) == str(camera_id)
    ]
    if not analyses:
        return None
    return max(analyses, key=lambda record: record.get("captured_at") or "")


@router.get("/cameras")
def list_cameras(store: Any = None) -> list[dict[str, Any]]:
    """Return a lightweight summary for each camera seen in persisted analyses."""
    return build_camera_summaries(store=store)


@router.get("/cameras/{camera_id}")
def get_camera(camera_id: str, store: Any = None) -> dict[str, Any]:
    """Return the latest analysis detail for a single camera."""
    if store is None:
        store = JsonStore("data")

    record = _latest_analysis_for_camera(store, camera_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_id}")

    details = record.get("details") or {}
    capture_result = details.get("capture_result") or {}
    coordinates = _load_camera_coordinates()
    map_position = _build_map_position(
        camera_id,
        capture_result.get("district"),
        capture_result.get("sub_district"),
        record,
        capture_result,
        coordinates,
    )
    return {
        "camera_id": camera_id,
        "captured_at": record.get("captured_at"),
        "label": record.get("label"),
        "density": _resolve_density(record, details),
        "name": capture_result.get("name"),
        "district": capture_result.get("district"),
        "sub_district": capture_result.get("sub_district"),
        "stream_url": capture_result.get("stream_url"),
        "vehicle_count": details.get("vehicle_count"),
        "mean_confidence": details.get("mean_confidence"),
        "active_tracks": details.get("active_tracks"),
        "scene": details.get("scene"),
        "lighting": details.get("lighting"),
        "visibility": details.get("visibility"),
        "quality_flag": details.get("quality_flag"),
        "flow_rate_vph": details.get("flow_rate_vph"),
        "per_frame": details.get("per_frame") or [],
        "map_position": map_position,
    }


@router.get("/cameras/{camera_id}/history")
def get_camera_history(
    camera_id: str,
    limit: int = Query(default=12, ge=1, le=200),
    store: Any = None,
) -> list[dict[str, Any]]:
    """Return recent analysis summaries for a camera, oldest to newest."""
    if store is None:
        store = JsonStore("data")

    analyses = [
        record
        for record in _load_analyses(store)
        if str(record.get("camera_id")) == str(camera_id)
    ]
    analyses.sort(key=lambda record: record.get("captured_at") or "")
    history = [
        {
            "captured_at": record.get("captured_at"),
            "density": _resolve_density(record, record.get("details") or {}),
            "vehicle_count": (record.get("details") or {}).get("vehicle_count"),
            "flow_rate_vph": (record.get("details") or {}).get("flow_rate_vph"),
        }
        for record in analyses
    ]
    # `limit` arrives as an int over HTTP, but is a Query object when the view
    # is invoked directly (e.g. in unit tests). Resolve the concrete value.
    limit_value = limit if isinstance(limit, int) else int(getattr(limit, "default", 12))
    return history[-limit_value:]
