"""Configuration defaults for the traffic cam pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Simple settings object for the initial scaffold."""

    dsat_index_url: str = os.getenv("DSAT_INDEX_URL", "https://www.dsat.gov.mo/dsat/realtime.aspx")
    output_dir: str = os.getenv("TRAFFIC_OUTPUT_DIR", "output")
    frame_count: int = int(os.getenv("FRAME_COUNT", "3"))
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "ffmpeg")
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))


settings = Settings()
