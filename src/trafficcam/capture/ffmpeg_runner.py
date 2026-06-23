"""Small wrapper around ffmpeg execution."""

from __future__ import annotations

import subprocess
from pathlib import Path


class FFmpegRunner:
    """Run ffmpeg for frame extraction."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self.ffmpeg_path = ffmpeg_path

    def capture_frame(self, stream_url: str, output_path: str | Path) -> None:
        """Run ffmpeg to capture a single frame from a stream URL."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [self.ffmpeg_path, "-y", "-i", stream_url, "-frames:v", "1", str(output_path)]
        subprocess.run(command, check=False, capture_output=True, text=True)
