"""Configuration defaults for the traffic cam pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    """Settings object with AI vision and analysis configuration."""

    # Discovery
    dsat_index_url: str = os.getenv("DSAT_INDEX_URL", "https://www.dsat.gov.mo/dsat/realtime.aspx")
    output_dir: str = os.getenv("TRAFFIC_OUTPUT_DIR", "output")
    frame_count: int = int(os.getenv("FRAME_COUNT", "3"))
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    # Vision model
    vision_model_name: str = os.getenv("VISION_MODEL", "google/owlvit-base-patch32")
    vision_device: str = os.getenv("VISION_DEVICE", "cpu")
    vision_confidence_threshold: float = float(os.getenv("VISION_CONFIDENCE", "0.25"))

    # Vehicle classes to detect (configurable list of text queries for zero-shot model)
    vehicle_queries: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv("VEHICLE_QUERIES", "car,truck,bus,motorcycle").split(",")
        )
    )

    # Density thresholds (vehicle count)
    density_threshold_light: int = int(os.getenv("DENSITY_LIGHT", "5"))
    density_threshold_moderate: int = int(os.getenv("DENSITY_MODERATE", "15"))
    density_threshold_heavy: int = int(os.getenv("DENSITY_HEAVY", "30"))

    # Scene classification thresholds
    scene_brightness_day_min: int = int(os.getenv("SCENE_BRIGHTNESS_DAY", "110"))
    scene_brightness_dusk_min: int = int(os.getenv("SCENE_BRIGHTNESS_DUSK", "60"))
    scene_low_visibility_edge_max: float = float(os.getenv("SCENE_LOW_VISIBILITY_EDGE", "0.05"))

    # Simple tracker settings (IoU-based)
    tracker_iou_threshold: float = float(os.getenv("TRACKER_IOU", "0.3"))
    tracker_max_age: int = int(os.getenv("TRACKER_MAX_AGE", "5"))

    # Periodic capture
    capture_interval_seconds: float = float(os.getenv("CAPTURE_INTERVAL", "60.0"))
    capture_max_cycles: int | None = int(os.getenv("CAPTURE_MAX_CYCLES", "0")) or None

    # Trend analysis
    trend_min_history: int = int(os.getenv("TREND_MIN_HISTORY", "6"))
    trend_z_threshold: float = float(os.getenv("TREND_Z_THRESHOLD", "2.0"))


settings = Settings()
