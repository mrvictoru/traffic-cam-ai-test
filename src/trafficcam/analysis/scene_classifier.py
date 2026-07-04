"""Scene classification scaffold."""

from __future__ import annotations

from pathlib import Path


class SceneClassifier:
    """Classify a scene as day or night using filename hints."""

    def classify(self, image_path: str) -> dict:
        """Return a simple scene classification derived from the provided path."""
        path = Path(image_path)
        name = path.stem.lower()
        if "night" in name or "dark" in name or "dusk" in name:
            return {"image_path": image_path, "scene": "night", "confidence": 0.8}
        if "day" in name or "sun" in name or "bright" in name:
            return {"image_path": image_path, "scene": "day", "confidence": 0.75}
        return {"image_path": image_path, "scene": "unknown", "confidence": 0.2}
