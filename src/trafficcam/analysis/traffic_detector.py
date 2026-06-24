"""High-level traffic density detector scaffold."""

from __future__ import annotations

from pathlib import Path


class TrafficDetector:
    """Return a lightweight density estimate based on the image filename."""

    def analyze(self, image_path: str) -> dict:
        """Return a simple analysis result derived from the provided path."""
        path = Path(image_path)
        name = path.stem.lower()
        if "heavy" in name or "jam" in name or "congest" in name:
            return {"image_path": image_path, "label": "heavy", "confidence": 0.85}
        if "light" in name or "free" in name:
            return {"image_path": image_path, "label": "light", "confidence": 0.8}
        if "moderate" in name or "slow" in name:
            return {"image_path": image_path, "label": "moderate", "confidence": 0.75}
        if "block" in name or "incident" in name:
            return {"image_path": image_path, "label": "blocked", "confidence": 0.9}
        return {"image_path": image_path, "label": "unknown", "confidence": 0.1}
