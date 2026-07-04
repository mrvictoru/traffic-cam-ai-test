"""Helpers for compact per-camera analysis indices."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .base import StorageBackend


@dataclass
class AnalysisIndexEntry:
    """Compact summary of one persisted analysis record."""

    captured_at: str
    density: str
    flow_total: int
    flow_nb: int
    flow_sb: int
    record_path: str


def build_index_entry(record: dict, record_path: str) -> AnalysisIndexEntry:
    """Project a full persisted analysis record into its compact index form."""
    details = record["details"]
    flow = details.get("flow_rate_vph", {})
    if not isinstance(flow, dict):
        flow = {"northbound": 0, "southbound": 0, "total": int(flow)}
    return AnalysisIndexEntry(
        captured_at=record["captured_at"],
        density=str(details.get("density", record.get("label", "unknown"))),
        flow_total=int(flow.get("total", 0)),
        flow_nb=int(flow.get("northbound", 0)),
        flow_sb=int(flow.get("southbound", 0)),
        record_path=record_path,
    )


def append_to_index(
    store: StorageBackend,
    camera_id: str,
    record: dict,
    record_path: str,
) -> None:
    """Append a single analysis record summary to the camera's JSONL index."""
    entry = build_index_entry(record, record_path)
    store.append_jsonl(f"analyses/{camera_id}/index.jsonl", asdict(entry))


def rebuild_camera_index(store: StorageBackend, camera_id: str) -> None:
    """Rebuild a camera's JSONL index from its persisted analysis records."""
    prefix = f"analyses/{camera_id}/"
    entries: list[dict] = []
    for record_path in store.list_records(prefix=prefix):
        if record_path.endswith("index.jsonl"):
            continue
        if not record_path.endswith(".json"):
            continue
        record = store.load_json(record_path)
        entries.append(asdict(build_index_entry(record, record_path)))
    entries.sort(key=lambda entry: entry["captured_at"])
    store.save_jsonl(f"analyses/{camera_id}/index.jsonl", entries)
