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
    vision_backend: str = os.getenv("VISION_BACKEND", "yolo")
    vision_model_name: str = os.getenv("VISION_MODEL", "google/owlv2-base-patch16-ensemble")
    vision_yolo_model_name: str = os.getenv("VISION_YOLO_MODEL", "yolov8n.pt")
    model_cache_dir: str = os.getenv("MODEL_CACHE_DIR", os.path.join(os.getcwd(), "model-cache"))
    huggingface_cache_dir: str = os.getenv(
        "HF_HOME",
        os.path.join(os.getenv("MODEL_CACHE_DIR", os.path.join(os.getcwd(), "model-cache")), "huggingface"),
    )
    ultralytics_cache_dir: str = os.getenv(
        "ULTRALYTICS_HOME",
        os.path.join(os.getenv("MODEL_CACHE_DIR", os.path.join(os.getcwd(), "model-cache")), "ultralytics"),
    )
    vision_yolo_weights_dir: str = os.getenv(
        "VISION_YOLO_WEIGHTS_DIR",
        os.path.join(
            os.getenv("ULTRALYTICS_HOME", os.path.join(os.getenv("MODEL_CACHE_DIR", os.path.join(os.getcwd(), "model-cache")), "ultralytics")),
            "weights",
        ),
    )
    vision_device: str = os.getenv("VISION_DEVICE", "cpu")
    vision_confidence_threshold: float = float(os.getenv("VISION_CONFIDENCE", "0.3"))

    # Object classes to detect (configurable list of text queries for zero-shot model)
    # Broader queries improve recall on varied camera angles and distances
    vehicle_queries: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv(
                "VEHICLE_QUERIES",
                "vehicle,car,truck,bus,motorcycle,van,taxi,suv",
            ).split(",")
        )
    )
    vision_vehicle_classes: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            os.getenv(
                "VISION_VEHICLE_CLASSES",
                "car,truck,bus,motorcycle,bicycle",
            ).split(",")
        )
    )

    # Density thresholds (vehicle count)
    density_threshold_light: int = int(os.getenv("DENSITY_LIGHT", "5"))
    density_threshold_moderate: int = int(os.getenv("DENSITY_MODERATE", "15"))
    density_threshold_heavy: int = int(os.getenv("DENSITY_HEAVY", "30"))
    night_heavy_min_confidence: float = float(os.getenv("NIGHT_HEAVY_MIN_CONFIDENCE", "0.4"))
    night_blocked_min_confidence: float = float(os.getenv("NIGHT_BLOCKED_MIN_CONFIDENCE", "0.5"))
    night_density_downgrade_steps: int = int(os.getenv("NIGHT_DENSITY_DOWNGRADE_STEPS", "1"))

    # Scene classification thresholds
    scene_brightness_day_min: int = int(os.getenv("SCENE_BRIGHTNESS_DAY", "110"))
    scene_brightness_dusk_min: int = int(os.getenv("SCENE_BRIGHTNESS_DUSK", "60"))
    scene_low_visibility_edge_max: float = float(os.getenv("SCENE_LOW_VISIBILITY_EDGE", "0.05"))

    # Simple tracker settings (IoU-based)
    tracker_backend: str = os.getenv("TRACKER_BACKEND", "auto")
    tracker_iou_threshold: float = float(os.getenv("TRACKER_IOU", "0.3"))
    tracker_max_age: int = int(os.getenv("TRACKER_MAX_AGE", "5"))
    supervision_track_activation_threshold: float = float(
        os.getenv("SUPERVISION_TRACK_ACTIVATION", "0.25")
    )
    supervision_lost_track_buffer: int = int(os.getenv("SUPERVISION_LOST_TRACK_BUFFER", "30"))
    supervision_minimum_matching_threshold: float = float(
        os.getenv("SUPERVISION_MATCHING_THRESHOLD", "0.8")
    )
    supervision_minimum_consecutive_frames: int = int(
        os.getenv("SUPERVISION_MIN_CONSECUTIVE_FRAMES", "1")
    )
    supervision_debug_frames_enabled: bool = os.getenv(
        "SUPERVISION_DEBUG_FRAMES", "0"
    ).strip() in {"1", "true", "yes", "on"}
    supervision_debug_dirname: str = os.getenv("SUPERVISION_DEBUG_DIRNAME", "debug")

    # Periodic capture
    capture_interval_seconds: float = float(os.getenv("CAPTURE_INTERVAL", "60.0"))
    capture_max_cycles: int | None = int(os.getenv("CAPTURE_MAX_CYCLES", "0")) or None
    capture_burst_fps: float = float(os.getenv("CAPTURE_BURST_FPS", "1.0"))
    capture_warmup_seconds: float = float(os.getenv("CAPTURE_WARMUP_SECONDS", "0.0"))
    roi_config_path: str = os.getenv("ROI_CONFIG_PATH", "config/camera_rois.json")
    roi_filter_enabled: bool = os.getenv("ROI_FILTER_ENABLED", "0").strip() in {"1", "true", "yes", "on"}
    flow_line_config_path: str = os.getenv("FLOW_LINE_CONFIG_PATH", "config/camera_flow_lines.json")

    # Trend analysis
    trend_min_history: int = int(os.getenv("TREND_MIN_HISTORY", "6"))
    trend_z_threshold: float = float(os.getenv("TREND_Z_THRESHOLD", "2.0"))


settings = Settings()
