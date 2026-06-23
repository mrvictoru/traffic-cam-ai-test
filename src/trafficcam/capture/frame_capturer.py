"""Orchestrate frame capture jobs."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Iterable, List

from ..models import CameraFeed, CaptureResult
from .ffmpeg_runner import FFmpegRunner


class FrameCapturer:
    """Capture frames from discovered manifests or camera feed objects."""

    def __init__(self, output_dir: str | Path | None = None, ffmpeg_runner: FFmpegRunner | None = None) -> None:
        self.output_dir = Path(output_dir or "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_runner = ffmpeg_runner or FFmpegRunner()

    def capture(self, cameras: Iterable[CameraFeed], frame_count: int = 1) -> List[CaptureResult]:
        """Capture placeholder outputs for each camera."""
        results: List[CaptureResult] = []
        for camera in cameras:
            output_path = self.output_dir / f"{camera.camera_id}_frame.jpg"
            output_path.write_bytes(b"placeholder")
            results.append(
                CaptureResult(
                    camera_id=camera.camera_id,
                    output_path=str(output_path),
                    success=True,
                    notes="placeholder capture scaffold",
                )
            )
        return results

    def capture_frames_from_manifest(self, manifest: dict, frame_count: int = 3, ffmpeg_path: list[str] | None = None) -> list[dict]:
        """Capture frames from a feed manifest into the configured output directory."""
        output_root = self.output_dir
        output_root.mkdir(parents=True, exist_ok=True)
        ffmpeg_path = ffmpeg_path or [self.ffmpeg_runner.ffmpeg_path]

        results = []
        for camera in manifest.get("cameras", []):
            stream_urls = camera.get("stream_urls") or []
            stream_url = next((url for url in stream_urls if str(url).lower().endswith(".m3u8")), None)
            if not stream_url:
                continue

            camera_output_dir = output_root / f"cam_{camera['cam_id']}"
            camera_output_dir.mkdir(parents=True, exist_ok=True)
            frame_pattern = str(camera_output_dir / "frame_%03d.jpg")

            command = [*ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", stream_url, "-frames:v", str(frame_count), frame_pattern]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
            frame_paths = sorted(camera_output_dir.glob("frame_*.jpg"))
            results.append(
                {
                    "cam_id": camera["cam_id"],
                    "stream_url": stream_url,
                    "returncode": completed.returncode,
                    "frame_paths": [str(path) for path in frame_paths],
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )

        return results

    def capture_frames_loop(self, index_url: str, output_root: str | Path | None = None, frame_count: int = 3, interval_seconds: float = 5.0, max_cycles: int | None = None, ffmpeg_path: list[str] | None = None) -> list[dict]:
        """Continuously capture multiple frames over time."""
        output_root = Path(output_root or self.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        self.output_dir = output_root

        cycle = 0
        all_results = []
        while max_cycles is None or cycle < max_cycles:
            from ..ingestion.dsat_client import DSATClient

            client = DSATClient(index_url=index_url)
            manifest = client.build_manifest()
            results = self.capture_frames_from_manifest(manifest, frame_count=frame_count, ffmpeg_path=ffmpeg_path)
            all_results.extend(results)
            cycle += 1
            if max_cycles is not None and cycle >= max_cycles:
                break
            time.sleep(interval_seconds)

        return all_results
