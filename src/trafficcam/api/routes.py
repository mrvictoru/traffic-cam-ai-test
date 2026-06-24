"""Route definitions for the API scaffold."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from trafficcam.storage.json_store import JsonStore

router = APIRouter()


@router.get("/cameras")
def list_cameras(store: Any = None) -> list[dict[str, Any]]:
    """Return a lightweight summary for each camera seen in persisted analyses."""
    if store is None:
        store = JsonStore("data")

    summaries: list[dict[str, Any]] = []
    analyses = [
        store.load_json(path)
        for path in store.list_records(prefix="analyses/")
        if path.endswith(".json")
    ]

    grouped: dict[str, dict[str, Any]] = {}
    for analysis in analyses:
        camera_id = analysis.get("camera_id") or "unknown"
        existing = grouped.setdefault(
            camera_id,
            {
                "camera_id": camera_id,
                "latest_density": None,
                "latest_captured_at": None,
                "latest_label": None,
            },
        )
        details = analysis.get("details", {})
        density = details.get("density") or analysis.get("label")
        captured_at = analysis.get("captured_at")
        if existing["latest_captured_at"] is None or (captured_at or "") >= (existing["latest_captured_at"] or ""):
            existing["latest_density"] = density
            existing["latest_captured_at"] = captured_at
            existing["latest_label"] = analysis.get("label")

    for summary in grouped.values():
        summaries.append(summary)

    return sorted(summaries, key=lambda item: item["camera_id"])
