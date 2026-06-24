"""Tests for traffic trend analysis: directional flow split, congestion duration,
and incident detection over persisted analysis records.

These tests drive the implementation of `trafficcam.analysis.trends.TrendAnalyzer`
and the supporting models in `trafficcam.models`.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from trafficcam.analysis.trends import (
    FlowSplit,
    TrendAnalyzer,
    compute_directional_flow_split,
)
from trafficcam.models import (
    AnalysisResult,
    CongestionEvent,
    IncidentEvent,
)
from trafficcam.storage.json_store import JsonStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(
    camera_id: str,
    ts: datetime,
    density: str,
    flow_total: int,
    flow_nb: int = 0,
    flow_sb: int = 0,
    total_count: int | None = None,
    confidence: float = 0.8,
) -> dict:
    """Build a persisted-analysis record dict in the canonical shape."""
    record = {
        "camera_id": camera_id,
        "label": density,  # density bucket stored in top-level label
        "confidence": confidence,
        "captured_at": ts.isoformat() + "Z",
        "details": {
            "density": density,
            "total_count": total_count if total_count is not None else _default_count(density),
            "flow_rate_vph": {
                "northbound": flow_nb,
                "southbound": flow_sb,
                "total": flow_total,
            },
        },
    }
    return record


def _default_count(density: str) -> int:
    return {"light": 3, "moderate": 12, "heavy": 25, "blocked": 40}.get(density, 0)


def _seed_store(tmp_path: Path, camera_id: str, records: list[dict]) -> JsonStore:
    """Persist a list of analysis records under the conventional layout."""
    store = JsonStore(tmp_path)
    for i, rec in enumerate(records):
        # Use the record's captured_at as the filename key (collision-safe via i)
        ts_key = rec["captured_at"].replace(":", "").replace("-", "")
        store.save_json(f"analyses/{camera_id}/{ts_key}_{i}.json", rec)
    return store


# ---------------------------------------------------------------------------
# compute_directional_flow_split (pure function over tracks)
# ---------------------------------------------------------------------------


def test_directional_flow_split_counts_each_track_once_per_direction():
    """A track crossing the line nb and another sb should produce (1, 1)."""
    line = ((0.0, 0.5), (1.0, 0.5))  # horizontal line at y=0.5
    tracks = [
        # track 1: starts below line, ends above -> northbound (y decreasing = up)
        [(0, 0, (0.5, 0.7)), (1, 1, (0.5, 0.4))],
        # track 2: starts above line, ends below -> southbound
        [(0, 0, (0.5, 0.3)), (1, 1, (0.5, 0.6))],
    ]
    split = compute_directional_flow_split(tracks, line)
    assert isinstance(split, FlowSplit)
    assert split.northbound == 1
    assert split.southbound == 1
    assert split.total == 2


def test_directional_flow_split_ignores_tracks_that_never_cross():
    tracks = [
        # stays above the line
        [(0, 0, (0.5, 0.3)), (1, 1, (0.5, 0.35))],
        # stays below the line
        [(0, 0, (0.5, 0.7)), (1, 1, (0.5, 0.65))],
    ]
    line = ((0.0, 0.5), (1.0, 0.5))
    split = compute_directional_flow_split(tracks, line)
    assert split.northbound == 0
    assert split.southbound == 0
    assert split.total == 0


def test_directional_flow_split_counts_track_only_once():
    """A single track that crosses the line multiple times in the same
    direction should be counted at most once per direction.

    Real tracking (e.g. BYTETracker) reuses the same track_id for the
    whole lifetime of a track, so all points in this trajectory share
    track_id=10.
    """
    line = ((0.0, 0.5), (1.0, 0.5))
    tracks = [
        # Single track crosses 3 times: nb, sb, nb -> counted as 1 nb + 1 sb.
        [
            (10, 0, (0.5, 0.6)),
            (10, 1, (0.5, 0.4)),  # nb
            (10, 2, (0.5, 0.6)),  # sb
            (10, 3, (0.5, 0.4)),  # nb (already counted)
        ],
    ]
    split = compute_directional_flow_split(tracks, line)
    assert split.northbound == 1
    assert split.southbound == 1
    assert split.total == 2


# ---------------------------------------------------------------------------
# TrendAnalyzer: congestion duration detection
# ---------------------------------------------------------------------------


def test_congestion_duration_detects_single_blocked_run(tmp_path: Path):
    """A contiguous run of 'blocked' records should yield one CongestionEvent."""
    base = datetime(2026, 6, 23, 9, 0, 0)
    # 3 cycles of 'blocked' at 5-minute intervals, then back to 'light'
    records = [
        _make_record("cam1", base, "blocked", 0),
        _make_record("cam1", base + timedelta(minutes=5), "blocked", 0),
        _make_record("cam1", base + timedelta(minutes=10), "blocked", 0),
        _make_record("cam1", base + timedelta(minutes=15), "light", 200),
    ]
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)

    events = analyzer.detect_congestion_events("cam1", density_levels={"blocked", "heavy"})

    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, CongestionEvent)
    assert ev.camera_id == "cam1"
    assert ev.density == "blocked"
    assert ev.start == base
    # 3 consecutive records at 5-min intervals = 10 minutes from first to last
    assert ev.duration == timedelta(minutes=10)
    assert ev.record_count == 3


def test_congestion_duration_detects_separate_runs_as_distinct_events(tmp_path: Path):
    """Two disjoint runs of congestion should produce two events."""
    base = datetime(2026, 6, 23, 9, 0, 0)
    records = [
        _make_record("cam1", base, "heavy", 50),
        _make_record("cam1", base + timedelta(minutes=5), "heavy", 50),
        _make_record("cam1", base + timedelta(minutes=10), "light", 200),
        _make_record("cam1", base + timedelta(minutes=15), "light", 200),
        _make_record("cam1", base + timedelta(minutes=20), "blocked", 0),
        _make_record("cam1", base + timedelta(minutes=25), "blocked", 0),
    ]
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)

    events = analyzer.detect_congestion_events(
        "cam1", density_levels={"heavy", "blocked"}
    )
    assert len(events) == 2
    assert events[0].density == "heavy"
    assert events[1].density == "blocked"
    assert events[0].record_count == 2
    assert events[1].record_count == 2


def test_congestion_duration_handles_no_records(tmp_path: Path):
    store = JsonStore(tmp_path)
    analyzer = TrendAnalyzer(store)
    events = analyzer.detect_congestion_events("nonexistent", density_levels={"heavy"})
    assert events == []


def test_congestion_duration_respects_density_level_set(tmp_path: Path):
    """Records with density 'moderate' should be ignored when not in the set."""
    base = datetime(2026, 6, 23, 9, 0, 0)
    records = [
        _make_record("cam1", base, "moderate", 100),
        _make_record("cam1", base + timedelta(minutes=5), "moderate", 100),
        _make_record("cam1", base + timedelta(minutes=10), "moderate", 100),
    ]
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)
    events = analyzer.detect_congestion_events(
        "cam1", density_levels={"heavy", "blocked"}
    )
    assert events == []


# ---------------------------------------------------------------------------
# TrendAnalyzer: incident detection (Option B)
# ---------------------------------------------------------------------------


def _seed_known_baseline(tmp_path: Path, camera_id: str, n: int, base_flow_total: int):
    """Seed N records with stable flow totals to build a clear baseline."""
    base = datetime(2026, 6, 23, 8, 0, 0)
    return [
        _make_record(
            camera_id,
            base + timedelta(minutes=5 * i),
            density="moderate",
            flow_total=base_flow_total,
        )
        for i in range(n)
    ]


def test_incident_detector_emits_flow_drop_event(tmp_path: Path):
    """A sudden flow drop well below baseline should produce an incident."""
    base = datetime(2026, 6, 23, 8, 0, 0)
    records = _seed_known_baseline(tmp_path, "cam1", 12, base_flow_total=200)
    # Add a sharp drop in the latest record
    records.append(
        _make_record("cam1", base + timedelta(minutes=60), "heavy", flow_total=20)
    )
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)

    incidents = analyzer.detect_incidents(
        "cam1",
        z_threshold=2.0,
        window_records=0,
        hour_buckets=1,
    )

    assert len(incidents) >= 1
    flow_drops = [i for i in incidents if i.incident_type == "flow_drop"]
    assert len(flow_drops) == 1
    ev = flow_drops[0]
    assert isinstance(ev, IncidentEvent)
    assert ev.camera_id == "cam1"
    assert ev.severity > 0  # some measure of how anomalous
    assert "flow_total" in ev.details
    assert ev.details["flow_total"] == 20


def test_incident_detector_emits_density_spike_event(tmp_path: Path):
    """A sudden density increase well above baseline should produce an incident."""
    base = datetime(2026, 6, 23, 8, 0, 0)
    records = []
    # Stable light density
    for i in range(12):
        records.append(
            _make_record(
                "cam1",
                base + timedelta(minutes=5 * i),
                density="light",
                flow_total=300,
            )
        )
    # Spike to blocked
    records.append(
        _make_record("cam1", base + timedelta(minutes=60), "blocked", flow_total=10)
    )
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)

    incidents = analyzer.detect_incidents(
        "cam1",
        z_threshold=2.0,
        window_records=0,
        hour_buckets=1,
    )

    density_spikes = [i for i in incidents if i.incident_type == "density_spike"]
    assert len(density_spikes) == 1
    ev = density_spikes[0]
    assert ev.camera_id == "cam1"
    assert ev.details["density"] == "blocked"


def test_incident_detector_emits_no_events_for_stable_history(tmp_path: Path):
    """Stable history with no anomalies should produce zero incidents."""
    records = _seed_known_baseline(tmp_path, "cam1", 20, base_flow_total=150)
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)
    incidents = analyzer.detect_incidents(
        "cam1",
        z_threshold=2.0,
        window_records=0,
        hour_buckets=1,
    )
    # No flow drops and no density spikes expected
    flow_drops = [i for i in incidents if i.incident_type == "flow_drop"]
    density_spikes = [i for i in incidents if i.incident_type == "density_spike"]
    assert flow_drops == []
    assert density_spikes == []


def test_incident_detector_persists_to_storage(tmp_path: Path):
    """Detected incidents should be persisted under incidents/{cam_id}/."""
    base = datetime(2026, 6, 23, 8, 0, 0)
    records = _seed_known_baseline(tmp_path, "cam1", 12, base_flow_total=200)
    records.append(
        _make_record("cam1", base + timedelta(minutes=60), "blocked", flow_total=10)
    )
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)

    analyzer.detect_incidents(
        "cam1",
        z_threshold=2.0,
        persist=True,
        window_records=0,
        hour_buckets=1,
    )

    incident_paths = list(store.list_records(prefix="incidents/cam1"))
    assert len(incident_paths) >= 1
    loaded = store.load_json(incident_paths[0])
    assert loaded["camera_id"] == "cam1"
    assert loaded["incident_type"] in {"flow_drop", "density_spike"}


def test_incident_detector_requires_minimum_history(tmp_path: Path):
    """With fewer than the minimum number of records, no incidents are computed."""
    records = [
        _make_record("cam1", datetime(2026, 6, 23, 8, 0, 0), "light", 100),
    ]
    store = _seed_store(tmp_path, "cam1", records)
    analyzer = TrendAnalyzer(store)
    incidents = analyzer.detect_incidents(
        "cam1",
        z_threshold=2.0,
        min_history=5,
        window_records=0,
        hour_buckets=1,
    )
    assert incidents == []


# ---------------------------------------------------------------------------
# Integration: end-to-end trend analysis
# ---------------------------------------------------------------------------


def test_trend_analyzer_handles_real_persisted_records(tmp_path: Path):
    """End-to-end: build records via AnalysisResult, persist, then analyze."""
    base = datetime(2026, 6, 23, 8, 0, 0)
    store = JsonStore(tmp_path)

    # Persist using AnalysisResult dataclass shape
    for i in range(10):
        rec = AnalysisResult(
            camera_id="cam1",
            label="moderate",
            confidence=0.7,
            captured_at=base + timedelta(minutes=5 * i),
            details={
                "density": "moderate",
                "total_count": 10,
                "flow_rate_vph": {"northbound": 50, "southbound": 50, "total": 100},
            },
        )
        store.save_json(
            f"analyses/cam1/{i:03d}.json",
            {**asdict(rec), "captured_at": rec.captured_at.isoformat() + "Z"},
        )

    analyzer = TrendAnalyzer(store)
    congestion = analyzer.detect_congestion_events("cam1", density_levels={"blocked"})
    assert congestion == []  # all moderate, not in level set
