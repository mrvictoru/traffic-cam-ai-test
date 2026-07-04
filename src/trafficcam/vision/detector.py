"""Zero-shot object detection using a vision-language model."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

# Lazy import - transformers is heavy and may not be installed in all envs
try:
    from transformers import pipeline

    _TRANSFORMERS_AVAILABLE = True
except Exception:  # pragma: no cover
    _TRANSFORMERS_AVAILABLE = False

try:
    from ultralytics import YOLO

    _ULTRALYTICS_AVAILABLE = True
except Exception:  # pragma: no cover
    _ULTRALYTICS_AVAILABLE = False


class ZeroShotDetector:
    """Detect vehicles in traffic camera frames.

    Supports configurable backends:
    - `owlvit`: open-vocabulary zero-shot object detection.
    - `yolo`: closed-set object detection using YOLO class labels.
    """

    def __init__(
        self,
        backend: str | None = None,
        model_name: str | None = None,
        device: str | None = None,
        confidence_threshold: float | None = None,
        queries: tuple[str, ...] | None = None,
        vehicle_classes: tuple[str, ...] | None = None,
    ) -> None:
        self.backend = (backend or settings.vision_backend).strip().lower()
        if self.backend not in {"owlvit", "yolo"}:
            raise ValueError(f"Unsupported vision backend: {self.backend}")

        if self.backend == "owlvit" and not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError(
                "transformers is required for owlvit backend. "
                "Install it with: pip install transformers torch"
            )
        if self.backend == "yolo" and not _ULTRALYTICS_AVAILABLE:
            raise RuntimeError(
                "ultralytics is required for yolo backend. "
                "Install it with: pip install ultralytics"
            )

        default_model = settings.vision_yolo_model_name if self.backend == "yolo" else settings.vision_model_name
        self.model_name = model_name or default_model
        self.device = device or settings.vision_device
        self.confidence_threshold = (
            confidence_threshold if confidence_threshold is not None else settings.vision_confidence_threshold
        )
        self.queries = queries or settings.vehicle_queries
        self.vehicle_classes = {
            cls_name.strip().lower()
            for cls_name in (vehicle_classes or settings.vision_vehicle_classes)
            if cls_name.strip()
        }
        self._pipeline: Any | None = None
        self._yolo_model: Any | None = None

    def _get_pipeline(self) -> Any:
        """Lazy-load the detection pipeline (cached)."""
        if self._pipeline is None:
            LOGGER.info(
                "Loading zero-shot detection model: %s (cache=%s)",
                self.model_name,
                settings.huggingface_cache_dir,
            )
            self._pipeline = pipeline(
                "zero-shot-object-detection",
                model=self.model_name,
                device=self.device,
                model_kwargs={"cache_dir": settings.huggingface_cache_dir},
            )
        return self._pipeline

    def _resolve_yolo_model_source(self) -> str:
        """Prefer the host-mounted cache before falling back to local files or downloads."""
        model_path = Path(self.model_name)
        cached_candidate = Path(settings.vision_yolo_weights_dir) / model_path.name
        if cached_candidate.is_file():
            LOGGER.info("Using cached YOLO weights: %s", cached_candidate)
            return str(cached_candidate)

        if model_path.is_file():
            LOGGER.info("Using local YOLO weights file: %s", model_path)
            return str(model_path)

        return self.model_name

    def _get_yolo_model(self) -> Any:
        """Lazy-load the YOLO model (cached)."""
        if self._yolo_model is None:
            model_source = self._resolve_yolo_model_source()
            LOGGER.info(
                "Loading YOLO detection model: %s (cache=%s)",
                model_source,
                settings.vision_yolo_weights_dir,
            )
            self._yolo_model = YOLO(model_source)
        return self._yolo_model

    @staticmethod
    def _density_payload(image_path: str, detections: list[dict[str, Any]]) -> dict[str, Any]:
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

    def _analyze_owlvit(self, image_path: str) -> dict[str, Any]:
        pipe = self._get_pipeline()
        results = pipe(image_path, candidate_labels=list(self.queries))

        detections: list[dict[str, Any]] = []
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

        payload = self._density_payload(image_path, detections)
        payload["backend"] = self.backend
        payload["model_name"] = self.model_name
        return payload

    def _analyze_yolo(self, image_path: str) -> dict[str, Any]:
        model = self._get_yolo_model()
        results = model.predict(
            source=image_path,
            conf=self.confidence_threshold,
            device=self.device,
            verbose=False,
        )

        detections: list[dict[str, Any]] = []
        if results:
            result = results[0]
            names = result.names or {}
            boxes = result.boxes
            if boxes is not None:
                for idx in range(len(boxes)):
                    box = boxes[idx]
                    confidence = float(box.conf.item())
                    cls_id = int(box.cls.item())
                    label_name = names[cls_id] if isinstance(names, dict) else str(names[cls_id])
                    label = str(label_name).lower()
                    if self.vehicle_classes and label not in self.vehicle_classes:
                        continue

                    xyxy = box.xyxy[0].tolist()
                    detections.append(
                        {
                            "label": label,
                            "confidence": confidence,
                            "box": {
                                "xmin": float(xyxy[0]),
                                "ymin": float(xyxy[1]),
                                "xmax": float(xyxy[2]),
                                "ymax": float(xyxy[3]),
                            },
                        }
                    )

        payload = self._density_payload(image_path, detections)
        payload["backend"] = self.backend
        payload["model_name"] = self.model_name
        return payload

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
        image = Path(image_path)
        if not image.exists():
            raise FileNotFoundError(image_path)
        if self.backend == "yolo":
            return self._analyze_yolo(image_path)
        return self._analyze_owlvit(image_path)

    def analyze_burst(self, frame_paths: list[str]) -> list[dict[str, Any]]:
        """Analyze a burst of frames and return per-frame results."""
        return [self.analyze(path) for path in frame_paths]

