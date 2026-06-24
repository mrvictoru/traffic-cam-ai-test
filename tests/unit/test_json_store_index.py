"""Tests for JsonStore indexing helpers and prefix-safe record listing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from trafficcam.analysis.trends import TrendAnalyzer
from trafficcam.storage.index import append_to_index, rebuild_camera_index
from trafficcam.storage.json_store import JsonStore


def _record(ts: datetime, flow_total: int, density: str = "moderate") -> dict:
    return {
        "camera_id": "cam1",
        "captured_at": ts.isoformat() + "Z",
        "label": density,
        "details": {
            "density": density,
            "flow_rate_vph": {"northbound": 4, "southbound": 6, "total": flow_total},
        },
    }


def test_jsonl_round_trip(tmp_path: Path):
    store = JsonStore(tmp_path)
    path = "analyses/cam1/index.jsonl"

    store.append_jsonl(path, {"a": 1})
    store.append_jsonl(path, {"a": 2})

    assert store.load_jsonl(path) == [{"a": 1}, {"a": 2}]


def test_list_records_prefix_is_not_substring_match(tmp_path: Path):
    store = JsonStore(tmp_path)
    store.save_json("analyses/cam1/001.json", {"ok": True})
    store.save_json("analyses/cam10/001.json", {"ok": True})

    results = list(store.list_records(prefix="analyses/cam1/"))

    assert results == ["analyses/cam1/001.json"]


def test_rebuild_camera_index_creates_jsonl_entries(tmp_path: Path):
    store = JsonStore(tmp_path)
    record = _record(datetime(2026, 6, 24, 8, 0, 0), 100)
    store.save_json("analyses/cam1/001.json", record)

    rebuild_camera_index(store, "cam1")

    entries = store.load_jsonl("analyses/cam1/index.jsonl")
    assert len(entries) == 1
    assert entries[0]["flow_total"] == 100
    assert entries[0]["record_path"] == "analyses/cam1/001.json"


def test_append_to_index_appends_without_full_rebuild(tmp_path: Path):
    store = JsonStore(tmp_path)
    record = _record(datetime(2026, 6, 24, 8, 0, 0), 100)

    append_to_index(store, "cam1", record, "analyses/cam1/001.json")
    append_to_index(store, "cam1", _record(datetime(2026, 6, 24, 8, 5, 0), 110), "analyses/cam1/002.json")

    entries = store.load_jsonl("analyses/cam1/index.jsonl")
    assert [entry["flow_total"] for entry in entries] == [100, 110]


def test_trend_analyzer_uses_index_when_available(tmp_path: Path):
    store = JsonStore(tmp_path)
    record = _record(datetime(2026, 6, 24, 8, 0, 0), 100, density="blocked")
    store.save_json("analyses/cam1/001.json", record)
    append_to_index(store, "cam1", record, "analyses/cam1/001.json")

    analyzer = TrendAnalyzer(store)
    records = analyzer.load_records("cam1")

    assert len(records) == 1
    assert records[0]["details"]["flow_rate_vph"]["total"] == 100
    assert records[0]["details"]["density"] == "blocked"
