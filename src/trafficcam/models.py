"""Data models for camera feeds, captures, and analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
