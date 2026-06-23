"""Parsing-related schema helpers for ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedCameraPage:
    """Represents the outcome of parsing a camera detail page."""

    camera_id: Optional[str] = None
    title: Optional[str] = None
    stream_url: Optional[str] = None
    image_url: Optional[str] = None
