"""Zero-shot object detection using a vision-language model."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

# Lazy import — transformers is heavy and may not be installed in all envs
try:
    from transformers import pipeline

    _TRANSFORMERS_AVAILABLE = True
except Exception:  # pragma: no cover
    _TRANSFORMERS_AVAILABLE = False


class ZeroShotDetector:
    """Detect vehicles in traffic camera frames using a zero-shot vision model.

    Uses a Hugging Face transformers pipeline (e.g. OWL-ViT) to detect objects
    from text queries without any task-specific training data.
    """

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        confidence_threshold: float | None = None,
        queries: tuple[str, ...] | None = None,
    ) -> None:
        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "transformers is required for ZeroShotDetector. "
                "Install it with: pip install transformers torch"
            )

        self.model_name = model_name or settings.vision_model_name
        self.device = device or settings.vision_device
        self.confidence_threshold = (
            confidence_threshold if confidence_threshold is not None else settings.vision_confidence_threshold
        )
        self.queries = queries or settings.vehicle_queries
        self._pipeline: Any | None = None

    def _get_pipeline(self) -> Any:
        """Lazy-load the detection pipeline (cached)."""
        if self._pipeline is None:
            LOGGER.info("Loading zero-shot detection model: %s", self.model_name)
            self._pipeline = pipeline(
                "zero-shot-object-detection",
                model=self.model_name,
                device=self.device,
            )
        return self._pipeline

    def analyze(self, image_path: str) -> dict[str, Any]:
        """Detect vehicles in a single image and return a structured result.

        Returns:
            {
                "image_path": str,
                "label": str,            # density bucket
                "confidence": float,     # mean detection confidence
                "detections": list[dict],
                "vehicle_count": int,
            }
        """
        pipe = self._get_pipeline()
        image = Path(image_path)
        if not image.exists():
            raise FileNotFoundError(image_path)

        results = pipe(image_path, candidate_labels=list(self.queries))

        detections: list[dict] = []
        for det in results:
            score = float(det.get("score", 0.0))
            if score < self.confidence_threshold:
                continue
            box = det.get("box", {})
            detections.append(
                {
                    "label": str(det.get("label", "unknown")),
                    "confidence": score,
                    "box": {
                        "xmin": float(box.get("xmin", 0)),
                        "ymin": float(box.get("ymin", 0)),
                        "xmax": float(box.get("xmax", 0)),
                        "ymax": float(box.get("ymax", 0)),
                    },
                }
            )

        vehicle_count = len(detections)
        mean_confidence = (
            float(np.mean([d["confidence"] for d in detections])) if detections else 0.0
        )

        from .density_scorer import DensityScorer

        density = DensityScorer().from_count(vehicle_count)

        return {
            "image_path": image_path,
            "label": density,
            "confidence": round(mean_confidence, 4),
            "detections": detections,
            "vehicle_count": vehicle_count,
        }

    def analyze_burst(self, frame_paths: list[str]) -> list[dict[str, Any]]:
        """Analyze a burst of frames and return per-frame results."""
        return [self.analyze(path) for path in frame_paths]
