"""Route definitions for the API scaffold."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from trafficcam.calibration import load_camera_calibrations, summarize_calibration_coverage
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
_DENSITY_FROM_SCORE = (
    (75.0, "blocked"),
    (50.0, "heavy"),
    (25.0, "moderate"),
)
_CALIBRATION_MIN_HISTORY = 5
_CALIBRATION_OFFPEAK_START = 2
_CALIBRATION_OFFPEAK_END = 5
_OUTPUT_PREFIX = "output/"

# Cache for parsed analysis records keyed by the data directory's mtime so
# repeated API requests don't re-parse every JSON file on disk.
_ANALYSES_CACHE: dict[str, Any] = {"key": None, "records": None}


def _data_dir_signature(store: JsonStore) -> tuple[str, float] | None:
    root = Path(getattr(store, "root_dir", Path("data")))
    try:
        resolved = root.resolve()
        latest_mtime = 0.0
        for path in resolved.rglob("*"):
            if path.is_file():
                try:
                    latest_mtime = max(latest_mtime, path.stat().st_mtime_ns)
                except OSError:
                    continue
        return (str(resolved), latest_mtime)
    except OSError:
        return (str(Path("data").resolve()), 0.0)


def _load_analyses(store: JsonStore) -> list[dict[str, Any]]:
    signature = _data_dir_signature(store)
    if signature is not None and _ANALYSES_CACHE["key"] == signature and _ANALYSES_CACHE["records"] is not None:
        return _ANALYSES_CACHE["records"]
    records = [
        store.load_json(path)
        for path in store.list_records(prefix="analyses/")
        if path.endswith(".json")
    ]
    if signature is not None:
        _ANALYSES_CACHE["key"] = signature
        _ANALYSES_CACHE["records"] = records
    return records


def _normalize_output_path(path_value: Any) -> str | None:
    if not path_value:
        return None
    raw_path = Path(str(path_value).replace("\\", "/"))
    if raw_path.is_absolute():
        try:
            raw_path = raw_path.relative_to(Path.cwd())
        except ValueError:
            return None
    normalized = raw_path.as_posix().lstrip("/")
    if normalized == "output" or not normalized.startswith(_OUTPUT_PREFIX):
        return None
    return normalized


def _output_asset_url(path_value: Any, cache_bust: str | None = None) -> str | None:
    normalized = _normalize_output_path(path_value)
    if normalized is None:
        return None
    suffix = ""
    if cache_bust:
        safe_cache_bust = str(cache_bust).replace(" ", "T").replace("+", "Z")
        suffix = f"?v={safe_cache_bust}"
    return f"/{normalized}{suffix}"


def _debug_frame_output_path(frame_path: Any, debug_frames_dir: Any) -> str | None:
    normalized_frame = _normalize_output_path(frame_path)
    normalized_debug_dir = _normalize_output_path(debug_frames_dir)
    if normalized_frame is None or normalized_debug_dir is None:
        return None
    candidate = Path(normalized_debug_dir) / f"{Path(normalized_frame).stem}_tracked.jpg"
    candidate_path = Path.cwd() / candidate
    if not candidate_path.is_file():
        return None
    return candidate.as_posix()


def _enrich_per_frame(per_frame: list[dict[str, Any]], debug_frames_dir: Any, cache_bust: str | None = None) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for frame in per_frame:
        record = dict(frame)
        image_path = record.get("image_path")
        debug_image_path = _debug_frame_output_path(image_path, debug_frames_dir)
        record["image_url"] = _output_asset_url(image_path, cache_bust=cache_bust)
        record["debug_image_url"] = _output_asset_url(debug_image_path, cache_bust=cache_bust)
        record["display_image_url"] = record["debug_image_url"] or record["image_url"]
        enriched.append(record)
    return enriched


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


def _coordinates_from_map_percent(x_percent: float, y_percent: float) -> tuple[float, float]:
    """Project percentage-based fallback map positions back into lat/lon.

    Leaflet markers need real coordinates. Approximate markers still derive
    from district anchors and jitter, but they must be expressed as Macau
    lat/lon so they can be rendered on the geographic map.
    """
    lat_min = _MACAU_MAP_BOUNDS["lat_min"]
    lat_max = _MACAU_MAP_BOUNDS["lat_max"]
    lon_min = _MACAU_MAP_BOUNDS["lon_min"]
    lon_max = _MACAU_MAP_BOUNDS["lon_max"]
    longitude = lon_min + ((x_percent / 100.0) * (lon_max - lon_min))
    latitude = lat_min + (((100.0 - y_percent) / 100.0) * (lat_max - lat_min))
    return round(latitude, 6), round(longitude, 6)


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
    x_percent = round(_clamp(anchor_x + x_jitter, 6.0, 94.0), 1)
    y_percent = round(_clamp(anchor_y + y_jitter, 6.0, 94.0), 1)
    latitude, longitude = _coordinates_from_map_percent(x_percent, y_percent)
    return {
        "x_percent": x_percent,
        "y_percent": y_percent,
        "source": "approximate",
        "latitude": latitude,
        "longitude": longitude,
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


def _save_camera_coordinates(path: Path, payload: dict[str, dict[str, Any]]) -> None:
    """Persist camera coordinates atomically to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps({"cameras": payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _resolve_density(analysis: dict[str, Any], details: dict[str, Any]) -> str:
    """Return the best available congestion label for an analysis record."""
    return str(details.get("density") or analysis.get("label") or "unknown")


def _calibration_status(camera_id: str, calibrations: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry = calibrations.get(str(camera_id)) or {}
    freeflow = entry.get("freeflow_px_per_frame")
    if not isinstance(freeflow, (int, float)):
        return {
            "status": "uncalibrated",
            "is_calibrated": False,
            "freeflow_px_per_frame": None,
            "sample_count": None,
            "offpeak_hours": None,
        }
    sample_count = entry.get("sample_count")
    if isinstance(sample_count, float) and sample_count.is_integer():
        sample_count = int(sample_count)
    return {
        "status": "calibrated",
        "is_calibrated": True,
        "freeflow_px_per_frame": float(freeflow),
        "sample_count": sample_count if isinstance(sample_count, int) else None,
        "offpeak_hours": str(entry.get("offpeak_hours")) if entry.get("offpeak_hours") else None,
    }


def _density_from_score(score: float | None) -> str:
    if score is None:
        return "unknown"
    for threshold, label in _DENSITY_FROM_SCORE:
        if score >= threshold:
            return label
    return "light"


def _camera_point(camera: dict[str, Any]) -> tuple[float, float] | None:
    latitude = _coerce_coordinate(camera.get("latitude"))
    longitude = _coerce_coordinate(camera.get("longitude"))
    if latitude is not None and longitude is not None:
        return latitude, longitude
    position = camera.get("map_position") or {}
    latitude = _coerce_coordinate(position.get("latitude"))
    longitude = _coerce_coordinate(position.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return latitude, longitude


def _corridor_group_key(camera: dict[str, Any]) -> tuple[str, str]:
    district = str(camera.get("district") or "unknown")
    sub_district = str(camera.get("sub_district") or district)
    return district, sub_district


def _distance_sq(left: tuple[float, float], right: tuple[float, float]) -> float:
    return ((left[0] - right[0]) ** 2) + ((left[1] - right[1]) ** 2)


def _load_camera_corridors(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path or os.getenv("CAMERA_CORRIDORS_PATH", "config/camera_corridors.json"))
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    corridors = payload.get("corridors") if isinstance(payload, dict) else None
    if not isinstance(corridors, list):
        return []
    return [corridor for corridor in corridors if isinstance(corridor, dict)]


def _build_corridor_segments(
    summaries: list[dict[str, Any]],
    corridors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    cameras_by_id = {str(camera.get("camera_id")): camera for camera in summaries}
    segments: list[dict[str, Any]] = []
    for index, corridor in enumerate(corridors if corridors is not None else _load_camera_corridors()):
        camera_ids = [str(camera_id) for camera_id in corridor.get("camera_ids", [])]
        cameras = [cameras_by_id[camera_id] for camera_id in camera_ids if camera_id in cameras_by_id]
        if len(cameras) < 2:
            continue
        corridor_name = str(corridor.get("name") or corridor.get("corridor_id") or f"corridor-{index + 1}")
        for segment_index, (left, right) in enumerate(zip(cameras, cameras[1:]), start=1):
            left_point = _camera_point(left)
            right_point = _camera_point(right)
            if left_point is None or right_point is None or left_point == right_point:
                continue
            scores = [
                float(score)
                for score in (left.get("latest_congestion_score"), right.get("latest_congestion_score"))
                if isinstance(score, (int, float))
            ]
            average_score = round(sum(scores) / len(scores), 2) if scores else None
            density = _density_from_score(average_score)
            segments.append(
                {
                    "segment_id": f"{corridor_name}:{segment_index}",
                    "corridor_id": str(corridor.get("corridor_id") or corridor_name),
                    "name": corridor_name,
                    "district": corridor.get("district") or left.get("district"),
                    "sub_district": corridor.get("sub_district") or left.get("sub_district"),
                    "camera_ids": [left.get("camera_id"), right.get("camera_id")],
                    "start": {"latitude": left_point[0], "longitude": left_point[1]},
                    "end": {"latitude": right_point[0], "longitude": right_point[1]},
                    "average_score": average_score,
                    "density": density,
                    "is_approximate": any(
                        ((camera.get("map_position") or {}).get("source") or "approximate") != "coordinates"
                        for camera in (left, right)
                    ),
                }
            )
    return segments


def _overview_calibration_summary(store: JsonStore) -> dict[str, Any]:
    manifest_camera_ids = [
        str(camera.get("cam_id"))
        for camera in _load_manifest_cameras()
        if camera.get("cam_id")
    ]
    camera_ids = manifest_camera_ids or [
        str(camera.get("camera_id"))
        for camera in build_camera_summaries(store=store)
        if camera.get("camera_id")
    ]
    summary = summarize_calibration_coverage(
        camera_ids,
        Path(getattr(store, "root_dir", Path("data"))),
        Path(os.getenv("CAMERA_SPEED_CALIBRATION_PATH", "config/camera_speed_calibration.json")),
        min_history=_CALIBRATION_MIN_HISTORY,
        offpeak_start=_CALIBRATION_OFFPEAK_START,
        offpeak_end=_CALIBRATION_OFFPEAK_END,
    )
    status_counts = dict(summary.get("status_counts") or {})
    return {
        "configured": int(summary.get("configured_count") or 0),
        "missing": int(summary.get("missing_count") or 0),
        "ready": int(status_counts.get("ready") or 0),
        "insufficient_history": int(status_counts.get("insufficient_history") or 0),
        "missing_motion_history": int(status_counts.get("missing_motion_history") or 0),
        "no_offpeak_history": int(status_counts.get("no_offpeak_history") or 0),
        "no_history": int(status_counts.get("no_history") or 0),
        "offpeak_hours": summary.get("offpeak_hours"),
        "min_history": int(summary.get("min_history") or _CALIBRATION_MIN_HISTORY),
        "next_ready_camera_ids": list((summary.get("status_camera_ids") or {}).get("ready", []))[:5],
    }


_MANIFEST_PATH = Path(os.getenv("CAMERA_MANIFEST_PATH", "data/manifest.json"))


def _load_manifest_cameras(path: Path | None = None) -> list[dict[str, Any]]:
    """Load cameras from the discovery manifest.

    Returns an empty list when the file is missing or invalid so the dashboard
    can still show whatever cameras have analysis records.
    """
    target = path or _MANIFEST_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cameras = payload.get("cameras")
    if not isinstance(cameras, list):
        return []
    return [entry for entry in cameras if isinstance(entry, dict)]


def build_camera_summaries(store: Any = None) -> list[dict[str, Any]]:
    """Return camera summaries enriched with congestion and map-position metadata.

    Cameras from the discovery manifest are always included so newly discovered
    feeds appear on the dashboard before their first analysis run completes;
    those entries simply carry "unknown" congestion until data exists.
    """
    if store is None:
        store = JsonStore("data")

    coordinates = _load_camera_coordinates()
    calibrations = load_camera_calibrations()
    analyses = _load_analyses(store)
    # Seed grouped entries from the manifest first. Analysis records below
    # enrich these entries; cameras without any history stay visible.
    manifest_cameras = {
        str(camera.get("cam_id")): camera
        for camera in _load_manifest_cameras()
        if camera.get("cam_id")
    }
    grouped: dict[str, dict[str, Any]] = {}
    for cam_id, camera in manifest_cameras.items():
        grouped[cam_id] = {
            "camera_id": cam_id,
            "name": camera.get("name"),
            "district": camera.get("district"),
            "sub_district": camera.get("sub_district"),
            "latest_density": "unknown",
            "latest_captured_at": None,
            "latest_label": None,
            "latest_congestion_score": None,
            "latest_vehicle_count": None,
            "latest_flow_total": None,
            "latest_flow_split": None,
            "latitude": None,
            "longitude": None,
            "density_rank": _DENSITY_PRIORITY["unknown"],
            "map_position": None,
            "calibration": _calibration_status(cam_id, calibrations),
        }
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
                "latest_congestion_score": None,
                "latest_vehicle_count": None,
                "latest_flow_total": None,
                "latest_flow_split": None,
                "latitude": None,
                "longitude": None,
                "density_rank": _DENSITY_PRIORITY["unknown"],
                "map_position": None,
                "calibration": _calibration_status(camera_id, calibrations),
            },
        )
        if not existing.get("name"):
            existing["name"] = capture_result.get("name")
        # Manifest metadata fills identity gaps so cameras discovered but not
        # yet analyzed still show proper names and district info.
        manifest_entry = manifest_cameras.get(str(camera_id))
        if manifest_entry:
            existing["name"] = existing.get("name") or manifest_entry.get("name")
            existing["district"] = existing.get("district") or manifest_entry.get("district")
            existing["sub_district"] = existing.get("sub_district") or manifest_entry.get("sub_district")
        if not existing.get("district"):
            existing["district"] = capture_result.get("district")
        if not existing.get("sub_district"):
            existing["sub_district"] = capture_result.get("sub_district")
        if existing["latest_captured_at"] is None or (captured_at or "") >= (existing["latest_captured_at"] or ""):
            existing["latest_density"] = density
            existing["latest_captured_at"] = captured_at
            existing["latest_label"] = analysis.get("label")
            existing["latest_congestion_score"] = details.get("congestion_score")
            existing["latest_vehicle_count"] = details.get("vehicle_count")
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

    # Ensure manifest-only cameras (no analysis records yet) also get map
    # positions so they appear on the dashboard immediately after discovery.
    for camera_id, existing in grouped.items():
        if existing.get("map_position") is not None:
            continue
        existing["map_position"] = _build_map_position(
            camera_id,
            existing.get("district"),
            existing.get("sub_district"),
            {},
            {},
            coordinates,
        )
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


def _manifest_camera_by_id(camera_id: str) -> dict[str, Any] | None:
    for camera in _load_manifest_cameras():
        if str(camera.get("cam_id")) == str(camera_id):
            return camera
    return None


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
    manifest_camera = _manifest_camera_by_id(camera_id)
    if record is None:
        if manifest_camera is None:
            raise HTTPException(status_code=404, detail=f"Unknown camera: {camera_id}")

        coordinates = _load_camera_coordinates()
        map_position = _build_map_position(
            camera_id,
            manifest_camera.get("district"),
            manifest_camera.get("sub_district"),
            {},
            {},
            coordinates,
        )
        stream_urls = manifest_camera.get("stream_urls") or []
        stream_url = next((url for url in stream_urls if str(url).lower().endswith(".m3u8")), None)
        return {
            "camera_id": camera_id,
            "captured_at": None,
            "label": "unknown",
            "density": "unknown",
            "name": manifest_camera.get("name"),
            "district": manifest_camera.get("district"),
            "sub_district": manifest_camera.get("sub_district"),
            "stream_url": stream_url,
            "vehicle_count": None,
            "congestion_score": None,
            "coverage_ratio": None,
            "mean_confidence": None,
            "active_tracks": None,
            "scene": None,
            "lighting": None,
            "visibility": None,
            "quality_flag": None,
            "flow_rate_vph": {},
            "latest_frame_url": None,
            "latest_debug_frame_url": None,
            "latest_image_url": None,
            "per_frame": [],
            "map_position": map_position,
            "calibration": _calibration_status(camera_id, load_camera_calibrations()),
        }

    details = record.get("details") or {}
    capture_result = details.get("capture_result") or {}
    debug_frames_dir = capture_result.get("debug_frames_dir")
    per_frame = _enrich_per_frame(
        details.get("per_frame") or [],
        debug_frames_dir,
        cache_bust=record.get("captured_at"),
    )
    latest_frame = per_frame[-1] if per_frame else {}
    coordinates = _load_camera_coordinates()
    map_position = _build_map_position(
        camera_id,
        capture_result.get("district"),
        capture_result.get("sub_district"),
        record,
        capture_result,
        coordinates,
    )
    calibration = _calibration_status(camera_id, load_camera_calibrations())
    return {
        "camera_id": camera_id,
        "captured_at": record.get("captured_at"),
        "label": record.get("label"),
        "density": _resolve_density(record, details),
        "name": capture_result.get("name") or (manifest_camera or {}).get("name"),
        "district": capture_result.get("district") or (manifest_camera or {}).get("district"),
        "sub_district": capture_result.get("sub_district") or (manifest_camera or {}).get("sub_district"),
        "stream_url": capture_result.get("stream_url") or next(
            (
                url
                for url in ((manifest_camera or {}).get("stream_urls") or [])
                if str(url).lower().endswith(".m3u8")
            ),
            None,
        ),
        "vehicle_count": details.get("vehicle_count"),
        "congestion_score": details.get("congestion_score"),
        "coverage_ratio": details.get("coverage_ratio"),
        "mean_confidence": details.get("mean_confidence"),
        "active_tracks": details.get("active_tracks"),
        "scene": details.get("scene"),
        "lighting": details.get("lighting"),
        "visibility": details.get("visibility"),
        "quality_flag": details.get("quality_flag"),
        "flow_rate_vph": details.get("flow_rate_vph"),
        "latest_frame_url": latest_frame.get("image_url"),
        "latest_debug_frame_url": latest_frame.get("debug_image_url"),
        "latest_image_url": latest_frame.get("display_image_url"),
        "per_frame": per_frame,
        "map_position": map_position,
        "calibration": calibration,
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
            "congestion_score": (record.get("details") or {}).get("congestion_score"),
            "flow_rate_vph": (record.get("details") or {}).get("flow_rate_vph"),
        }
        for record in analyses
    ]
    limit_value = limit if isinstance(limit, int) else int(getattr(limit, "default", 12))
    return history[-limit_value:]


@router.put("/cameras/{camera_id}/position")
def update_camera_position(camera_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist manual camera coordinates so the marker can be dragged into place."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Position payload must be a JSON object")

    latitude = _coerce_coordinate(payload.get("latitude"))
    longitude = _coerce_coordinate(payload.get("longitude"))
    if latitude is None or longitude is None:
        raise HTTPException(status_code=400, detail="latitude and longitude are required")

    bounds = _MACAU_MAP_BOUNDS
    if not (bounds["lat_min"] <= latitude <= bounds["lat_max"]):
        raise HTTPException(status_code=422, detail="Latitude is outside Macau bounds")
    if not (bounds["lon_min"] <= longitude <= bounds["lon_max"]):
        raise HTTPException(status_code=422, detail="Longitude is outside Macau bounds")

    coords_path = Path(os.getenv("CAMERA_COORDS_PATH", str(Path("config") / "camera_coordinates.json")))
    coordinates = _load_camera_coordinates(coords_path)
    entry = dict(coordinates.get(str(camera_id), {}))
    entry["latitude"] = latitude
    entry["longitude"] = longitude

    if payload.get("name") is not None:
        name = str(payload.get("name")).strip()
        if name:
            entry["name"] = name
    if payload.get("bearing") is not None:
        bearing = _coerce_coordinate(payload.get("bearing"))
        if bearing is not None:
            entry["bearing"] = bearing

    coordinates[str(camera_id)] = entry
    _save_camera_coordinates(coords_path, coordinates)

    return {
        "camera_id": camera_id,
        "latitude": latitude,
        "longitude": longitude,
        "map_position": _map_position_from_coordinates(latitude, longitude),
    }


@router.get("/overview")
def get_overview(store: Any = None) -> dict[str, Any]:
    """City-wide congestion overview for the dashboard header cards."""
    if store is None:
        store = JsonStore("data")
    summaries = build_camera_summaries(store=store)
    corridor_segments = _build_corridor_segments(summaries)
    calibration_summary = _overview_calibration_summary(store)
    counts = {"light": 0, "moderate": 0, "heavy": 0, "blocked": 0, "unknown": 0}
    scores: list[float] = []
    for cam in summaries:
        counts[str(cam.get("latest_density") or "unknown").lower()] = (
            counts.get(str(cam.get("latest_density") or "unknown").lower(), 0) + 1
        )
        score = cam.get("latest_congestion_score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    worst = sorted(
        summaries,
        key=lambda c: (
            _DENSITY_PRIORITY.get(str(c.get("latest_density") or "unknown").lower(), 0),
            float(c.get("latest_congestion_score") or 0.0),
        ),
        reverse=True,
    )
    return {
        "camera_count": len(summaries),
        "density_counts": {k: v for k, v in counts.items() if k != "unknown"} | {"unknown": counts["unknown"]},
        "average_score": round(sum(scores) / len(scores), 2) if scores else None,
        "corridor_segments": corridor_segments,
        "calibration_summary": calibration_summary,
        "worst_cameras": [
            {
                "camera_id": c.get("camera_id"),
                "name": c.get("name"),
                "district": c.get("district"),
                "density": c.get("latest_density"),
                "congestion_score": c.get("latest_congestion_score"),
                "captured_at": c.get("latest_captured_at"),
            }
            for c in worst[:5]
        ],
    }
