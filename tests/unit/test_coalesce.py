"""Tests for incident coalescing on sustained anomalies."""

from __future__ import annotations

from datetime import datetime, timedelta

from trafficcam.analysis.coalesce import coalesce_incidents
from trafficcam.models import IncidentEvent


def _incident(ts: datetime, incident_type: str, severity: float, camera_id: str = "cam1") -> IncidentEvent:
    return IncidentEvent(
        camera_id=camera_id,
        incident_type=incident_type,
        timestamp=ts,
        severity=severity,
        details={},
    )


def test_sustained_outage_coalesces_to_one_incident():
    base = datetime(2026, 6, 24, 8, 0, 0)
    incidents = [_incident(base + timedelta(minutes=5 * i), "flow_drop", 2.0 + i) for i in range(6)]

    merged = coalesce_incidents(incidents, cooldown_minutes=10)

    assert len(merged) == 1
    assert merged[0].coalesced_count == 6
    assert len(merged[0].coalesced_timestamps) == 6
    assert merged[0].severity == 7.0


def test_different_types_do_not_coalesce():
    base = datetime(2026, 6, 24, 8, 0, 0)
    incidents = [
        _incident(base, "flow_drop", 2.0),
        _incident(base + timedelta(minutes=5), "density_spike", 3.0),
    ]

    merged = coalesce_incidents(incidents, cooldown_minutes=10)

    assert len(merged) == 2


def test_cooldown_boundary_starts_new_group():
    base = datetime(2026, 6, 24, 8, 0, 0)
    incidents = [
        _incident(base, "flow_drop", 2.0),
        _incident(base + timedelta(minutes=15), "flow_drop", 4.0),
    ]

    merged = coalesce_incidents(incidents, cooldown_minutes=10)

    assert len(merged) == 2
