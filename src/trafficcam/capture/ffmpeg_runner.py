"""Small wrapper around ffmpeg execution."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class FFmpegRunner:
    """Run ffmpeg for frame extraction."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self.ffmpeg_path = ffmpeg_path

    def capture_frame(self, stream_url: str, output_path: str | Path) -> None:
        """Run ffmpeg to capture a single frame from a stream URL."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.capture_frames(
            stream_url,
            output_path,
            frame_count=1,
            sample_fps=None,
        )

    def capture_frames(
        self,
        stream_url: str,
        output_path: str | Path,
        frame_count: int,
        sample_fps: float | None = None,
        warmup_seconds: float = 0.0,
        extra_args: Sequence[str] | None = None,
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        """Run ffmpeg to capture one or more frames from a stream URL.

        When `sample_fps` is set for multi-frame capture, ffmpeg samples frames over
        time instead of grabbing the first adjacent decode frames from the stream.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        command: list[str] = [self.ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"]
        if warmup_seconds > 0:
            command.extend(["-ss", str(warmup_seconds)])
        command.extend(["-i", stream_url])
        if sample_fps is not None and frame_count > 1:
            command.extend(["-vf", f"fps={sample_fps:g}"])
        if extra_args:
            command.extend(extra_args)
        command.extend(["-frames:v", str(frame_count), str(output_path)])
        return subprocess.run(command, check=False, capture_output=True, text=True, timeout=timeout)
