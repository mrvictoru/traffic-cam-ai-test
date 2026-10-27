"""Health and schema contracts shared across pipeline components."""

from __future__ import annotations

from typing import Any


CURRENT_ANALYSIS_SCHEMA_VERSION = 2


def observation_is_usable(record: dict[str, Any]) -> bool:
    """Return whether an analysis record is safe to use as traffic data.

    Records written by older versions did not carry health metadata and remain
    usable for display. Explicitly failed captures/analyses, and the legacy
    analysis error marker, are excluded from traffic history.
    """
    details = record.get("details") or {}
    if not isinstance(details, dict):
        details = {}
    health = record.get("health") or details.get("health") or {}
    if not isinstance(health, dict):
        return False
    if health.get("usable") is False:
        return False
    if str(health.get("overall") or "").lower() in {"failed", "unavailable"}:
        return False
    if details.get("analysis_error"):
        return False
    capture = health.get("capture") or details.get("capture_health") or {}
    if not isinstance(capture, dict):
        return False
    if str(capture.get("status") or "").lower() in {"failed", "partial", "unsupported"}:
        return False
    analysis = health.get("analysis") or {}
    if not isinstance(analysis, dict):
        return False
    return str(analysis.get("status") or "").lower() not in {"failed", "unavailable"}
