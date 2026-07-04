"""Helpers for coalescing sustained incidents into a single alert."""

from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from typing import Sequence

from ..models import CoalescedIncident, IncidentEvent


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).replace(tzinfo=None)


def coalesce_incidents(
    incidents: Sequence[IncidentEvent],
    *,
    cooldown_minutes: float = 10.0,
) -> list[CoalescedIncident]:
    """Collapse nearby incidents of the same type into one representative alert."""
    if not incidents:
        return []

    merged: list[CoalescedIncident] = []
    cooldown = timedelta(minutes=cooldown_minutes)

    for incident in sorted(incidents, key=lambda item: item.timestamp):
        if not merged:
            merged.append(
                CoalescedIncident(
                    camera_id=incident.camera_id,
                    incident_type=incident.incident_type,
                    timestamp=incident.timestamp,
                    severity=incident.severity,
                    details=dict(incident.details),
                    coalesced_count=1,
                    coalesced_timestamps=[incident.timestamp.isoformat() + "Z"],
                )
            )
            continue

        previous = merged[-1]
        previous_last_ts = _parse_timestamp(previous.coalesced_timestamps[-1])
        same_group = (
            previous.camera_id == incident.camera_id
            and previous.incident_type == incident.incident_type
            and incident.timestamp - previous_last_ts <= cooldown
        )
        if not same_group:
            merged.append(
                CoalescedIncident(
                    camera_id=incident.camera_id,
                    incident_type=incident.incident_type,
                    timestamp=incident.timestamp,
                    severity=incident.severity,
                    details=dict(incident.details),
                    coalesced_count=1,
                    coalesced_timestamps=[incident.timestamp.isoformat() + "Z"],
                )
            )
            continue

        previous.coalesced_count += 1
        previous.coalesced_timestamps.append(incident.timestamp.isoformat() + "Z")
        previous.severity = max(previous.severity, incident.severity)
        if incident.severity >= previous.severity:
            previous.details = dict(incident.details)

    return merged
