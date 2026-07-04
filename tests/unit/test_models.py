"""Direct unit tests for the trend/event data models.

These tests cover the dataclasses in `trafficcam.models` independently of
the analysis logic in `trafficcam.analysis.trends`, so the model shape
can be verified even when the higher-level algorithms are not used.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta

from trafficcam.models import (
    AnalysisResult,
    CoalescedIncident,
    CongestionEvent,
    FlowSplit,
    IncidentEvent,
)


# ---------------------------------------------------------------------------
# FlowSplit
# ---------------------------------------------------------------------------


def test_flow_split_total_sums_directional_counts():
    split = FlowSplit(northbound=3, southbound=5)
    assert split.total == 8
    assert split.to_dict() == {"northbound": 3, "southbound": 5, "total": 8}


def test_flow_split_from_dict_supports_directional_payload():
    payload = {"northbound": 4, "southbound": 6}
    split = FlowSplit.from_dict(payload)
    assert split.northbound == 4
    assert split.southbound == 6
    assert split.total == 10


def test_flow_split_from_dict_supports_legacy_scalar_total():
    """Legacy records only stored a scalar `total` with no breakdown."""
    split = FlowSplit.from_dict({"total": 7})
    assert split.northbound == 0
    assert split.southbound == 7
    assert split.total == 7


# ---------------------------------------------------------------------------
# CongestionEvent
# ---------------------------------------------------------------------------


def test_congestion_event_carries_duration_and_record_count():
    start = datetime(2026, 6, 24, 9, 0, 0)
    end = start + timedelta(minutes=15)
    event = CongestionEvent(
        camera_id="cam1",
        density="blocked",
        start=start,
        end=end,
        duration=end - start,
        record_count=3,
    )
    assert event.camera_id == "cam1"
    assert event.density == "blocked"
    assert event.duration == timedelta(minutes=15)
    assert event.record_count == 3
    payload = asdict(event)
    assert payload["camera_id"] == "cam1"
    assert payload["density"] == "blocked"


# ---------------------------------------------------------------------------
# IncidentEvent
# ---------------------------------------------------------------------------


def test_incident_event_default_details_is_empty_dict():
    event = IncidentEvent(
        camera_id="cam1",
        incident_type="flow_drop",
        timestamp=datetime(2026, 6, 24, 9, 0, 0),
        severity=2.5,
    )
    assert event.details == {}
    assert event.incident_type == "flow_drop"
    assert event.severity == 2.5


def test_incident_event_accepts_density_spike_type():
    event = IncidentEvent(
        camera_id="cam1",
        incident_type="density_spike",
        timestamp=datetime(2026, 6, 24, 9, 5, 0),
        severity=3.1,
        details={"density": "blocked", "z_score": 3.1},
    )
    assert event.incident_type == "density_spike"
    assert event.details["density"] == "blocked"


# ---------------------------------------------------------------------------
# CoalescedIncident
# ---------------------------------------------------------------------------


def test_coalesced_event_inherits_and_augments_incident():
    event = CoalescedIncident(
        camera_id="cam1",
        incident_type="flow_drop",
        timestamp=datetime(2026, 6, 24, 9, 0, 0),
        severity=2.5,
        coalesced_count=4,
        coalesced_timestamps=[
            "2026-06-24T09:00:00Z",
            "2026-06-24T09:05:00Z",
            "2026-06-24T09:10:00Z",
            "2026-06-24T09:15:00Z",
        ],
    )
    assert isinstance(event, IncidentEvent)
    assert event.coalesced_count == 4
    assert len(event.coalesced_timestamps) == 4


# ---------------------------------------------------------------------------
# AnalysisResult (existing model) - quick smoke test
# ---------------------------------------------------------------------------


def test_analysis_result_uses_utcnow_by_default():
    result = AnalysisResult(camera_id="cam1", label="moderate", confidence=0.5)
    assert result.camera_id == "cam1"
    assert result.label == "moderate"
    assert result.confidence == 0.5
    assert isinstance(result.captured_at, datetime)
    assert result.details == {}
