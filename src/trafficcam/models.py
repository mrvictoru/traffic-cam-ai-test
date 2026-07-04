"""Data models for camera feeds, captures, analysis results, and trend events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional


@dataclass
class CameraFeed:
    """Represents a discovered camera feed."""

    camera_id: str
    name: str
    detail_url: str
    stream_url: Optional[str] = None
    source: str = "dsat"
    metadata: dict = field(default_factory=dict)


@dataclass
class CaptureResult:
    """Represents a single frame capture attempt."""

    camera_id: str
    output_path: str
    success: bool
    captured_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""


@dataclass
class AnalysisResult:
    """Represents a traffic analysis result for a captured frame."""

    camera_id: str
    label: str
    confidence: float
    captured_at: datetime = field(default_factory=datetime.utcnow)
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Trend / event models (Phase 4 Option B: post-hoc temporal analysis)
# ---------------------------------------------------------------------------


@dataclass
class FlowSplit:
    """Directional flow split for a single analysis cycle.

    `northbound` and `southbound` are int counts of unique vehicles crossing
    the configured counting line in each direction. `total` is the sum
    (kept for backward-compatibility with consumers that previously read a
    scalar `flow_rate_vph`).
    """

    northbound: int = 0
    southbound: int = 0

    @property
    def total(self) -> int:
        return self.northbound + self.southbound

    def to_dict(self) -> dict:
        return {
            "northbound": self.northbound,
            "southbound": self.southbound,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "FlowSplit":
        """Build from a persisted dict, tolerating legacy scalar `total` only."""
        if "northbound" in payload or "southbound" in payload:
            return cls(
                northbound=int(payload.get("northbound", 0)),
                southbound=int(payload.get("southbound", 0)),
            )
        # Legacy fallback: a scalar `total` with no directional breakdown.
        total = int(payload.get("total", 0))
        return cls(northbound=0, southbound=total)


@dataclass
class CongestionEvent:
    """A contiguous run of congestion-level density on a single camera."""

    camera_id: str
    density: str
    start: datetime
    end: datetime
    duration: timedelta
    record_count: int
    details: dict = field(default_factory=dict)


@dataclass
class IncidentEvent:
    """An anomalous event detected across a camera's analysis history.

    `incident_type` is one of: "flow_drop", "density_spike".
    `severity` is a non-negative float — for z-score based detection this is
    the absolute z-score of the anomalous reading vs the rolling baseline.
    """

    camera_id: str
    incident_type: str
    timestamp: datetime
    severity: float
    details: dict = field(default_factory=dict)


@dataclass
class CoalescedIncident(IncidentEvent):
    """Incident record augmented with cooldown-based grouping metadata."""

    coalesced_count: int = 1
    coalesced_timestamps: list[str] = field(default_factory=list)
