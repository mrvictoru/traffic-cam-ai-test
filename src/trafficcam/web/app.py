"""Minimal web app scaffold."""

from __future__ import annotations

from typing import Any

from trafficcam.storage.json_store import JsonStore


def render_dashboard(store: JsonStore | None = None) -> str:
    """Render a simple dashboard over persisted analyses."""
    if store is None:
        store = JsonStore("data")

    analyses = [
        store.load_json(path)
        for path in store.list_records(prefix="analyses/")
        if path.endswith(".json")
    ]
    rows = []
    for analysis in analyses:
        details = analysis.get("details", {})
        density = details.get("density") or analysis.get("label")
        rows.append(
            f"<li><strong>{analysis.get('camera_id', 'unknown')}</strong>: {density} at {analysis.get('captured_at', 'unknown')}</li>"
        )

    if not rows:
        return "<h1>Traffic Cam Dashboard</h1><p>No analyses available yet.</p>"

    return "<h1>Traffic Cam Dashboard</h1><ul>" + "".join(rows) + "</ul>"
