"""Helpers for selecting supported stream URLs from feed metadata."""

from __future__ import annotations

from urllib.parse import urlparse


def select_hls_url(stream_urls: object) -> str | None:
    """Return the first HLS URL while preserving its query string."""
    if not isinstance(stream_urls, (list, tuple)):
        return None
    for value in stream_urls:
        if not isinstance(value, str) or not value.strip():
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            continue
        if parsed.path.lower().endswith(".m3u8"):
            return value
    return None
