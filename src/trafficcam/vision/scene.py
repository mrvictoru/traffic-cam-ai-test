"""Scene classification for traffic camera frames.

Combines classical CV heuristics (brightness, contrast, edge density) with
optional zero-shot vision classification to determine viewing conditions.
Scene quality flags are used downstream to weight or gate analysis results.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

# Lazy import
try:
    from transformers import pipeline

    _TRANSFORMERS_AVAILABLE = True
except Exception:  # pragma: no cover
    _TRANSFORMERS_AVAILABLE = False


try:
    import cv2

    _CV2_AVAILABLE = True
except Exception:  # pragma: no cover
    _CV2_AVAILABLE = False


class SceneClassifier:
    """Classify scene lighting and visibility from a traffic camera frame.

    Uses fast classical heuristics by default; optionally uses a zero-shot
    vision model for richer scene understanding when transformers is installed.
    """

    def __init__(
        self,
        brightness_day_min: int | None = None,
        brightness_dusk_min: int | None = None,
        low_visibility_edge_max: float | None = None,
        use_zero_shot: bool = True,
    ) -> None:
        self.brightness_day_min = (
            brightness_day_min if brightness_day_min is not None else settings.scene_brightness_day_min
        )
        self.brightness_dusk_min = (
            brightness_dusk_min if brightness_dusk_min is not None else settings.scene_brightness_dusk_min
        )
        self.low_visibility_edge_max = (
            low_visibility_edge_max
            if low_visibility_edge_max is not None
            else settings.scene_low_visibility_edge_max
        )
        self.use_zero_shot = use_zero_shot and _TRANSFORMERS_AVAILABLE
        self._pipeline: Any | None = None

    def _get_pipeline(self) -> Any:
        """Lazy-load zero-shot classification pipeline."""
        if self._pipeline is None and self.use_zero_shot:
            LOGGER.info("Loading zero-shot scene classification model")
            self._pipeline = pipeline(
                "zero-shot-image-classification",
                model=settings.vision_model_name,
                device=settings.vision_device,
            )
        return self._pipeline

    @staticmethod
    def _compute_heuristics(image_path: str) -> dict[str, Any]:
        """Compute brightness, contrast, and edge density via OpenCV."""
        if not _CV2_AVAILABLE:
            LOGGER.warning("opencv not available; scene heuristics disabled")
            return {
                "brightness": 0.0,
                "contrast": 0.0,
                "edge_density": 0.0,
            }

        img = cv2.imread(str(image_path))
        if img is None:
            raise FileNotFoundError(image_path)

        # Brightness: mean of V channel in HSV
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        brightness = float(np.mean(hsv[:, :, 2]))

        # Contrast: standard deviation of grayscale luma
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        contrast = float(np.std(gray))

        # Edge density: Canny edge pixel ratio
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float(np.count_nonzero(edges) / edges.size)

        return {
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
            "edge_density": round(edge_density, 4),
        }

    def classify(self, image_path: str) -> dict[str, Any]:
        """Classify the scene and return structured info.

        Returns:
            {
                "image_path": str,
                "scene": str,           # day / dusk / night
                "lighting": str,        # day / dusk / night
                "visibility": str,      # clear / low_visibility
                "confidence": float,
                "heuristics": dict,     # brightness, contrast, edge_density
                "quality_flag": str,    # good / fair / poor
            }
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(image_path)

        heuristics = self._compute_heuristics(image_path)
        brightness = heuristics["brightness"]
        edge_density = heuristics["edge_density"]

        # Lighting from brightness
        if brightness >= self.brightness_day_min:
            lighting = "day"
        elif brightness >= self.brightness_dusk_min:
            lighting = "dusk"
        else:
            lighting = "night"

        # Visibility from edge density (fog/rain suppress edges)
        visibility = "clear" if edge_density >= self.low_visibility_edge_max else "low_visibility"

        # Quality flag: poor conditions reduce detection reliability
        if lighting == "night" or visibility == "low_visibility":
            quality_flag = "poor"
        elif lighting == "dusk":
            quality_flag = "fair"
        else:
            quality_flag = "good"

        confidence = 0.85

        # Optional zero-shot enrichment
        zero_shot_labels: dict[str, float] = {}
        if self.use_zero_shot:
            try:
                pipe = self._get_pipeline()
                if pipe is not None:
                    results = pipe(
                        image_path,
                        candidate_labels=[
                            "daytime traffic scene",
                            "nighttime traffic scene",
                            "foggy weather",
                            "rainy weather",
                            "clear weather",
                        ],
                    )
                    zero_shot_labels = {r["label"]: float(r["score"]) for r in results}
                    # Use zero-shot to boost confidence when models agree
                    day_score = zero_shot_labels.get("daytime traffic scene", 0.0)
                    night_score = zero_shot_labels.get("nighttime traffic scene", 0.0)
                    if lighting == "day" and day_score > 0.5:
                        confidence = min(0.99, confidence + 0.1)
                    elif lighting == "night" and night_score > 0.5:
                        confidence = min(0.99, confidence + 0.1)
            except Exception as exc:
                LOGGER.debug("Zero-shot scene classification failed: %s", exc)

        return {
            "image_path": image_path,
            "scene": lighting,
            "lighting": lighting,
            "visibility": visibility,
            "confidence": round(confidence, 4),
            "heuristics": heuristics,
            "quality_flag": quality_flag,
            "zero_shot_labels": zero_shot_labels,
        }
