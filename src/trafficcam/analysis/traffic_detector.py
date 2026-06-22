"""High-level traffic density detector scaffold."""

from __future__ import annotations


class TrafficDetector:
    """Placeholder traffic detector that returns a simple label."""

    def analyze(self, image_path: str) -> dict:
        """Return a simple placeholder analysis result."""
        return {"image_path": image_path, "label": "unknown", "confidence": 0.0}
