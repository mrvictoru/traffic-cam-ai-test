"""Orchestrate frame capture jobs."""

from __future__ import annotations

import math
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterable, List

from ..models import CameraFeed, CaptureResult
from ..config import settings
from .ffmpeg_runner import FFmpegRunner
from ..ingestion.stream_urls import select_hls_url

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


class FrameCapturer:
    """Capture frames from discovered manifests or camera feed objects."""

    def __init__(self, output_dir: str | Path | None = None, ffmpeg_runner: FFmpegRunner | None = None) -> None:
        self.output_dir = Path(output_dir or "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_runner = ffmpeg_runner or FFmpegRunner(settings.ffmpeg_path)

    def capture(self, cameras: Iterable[CameraFeed], frame_count: int = 1) -> List[CaptureResult]:
        """Reject the legacy object API until it has a real capture contract."""
        raise NotImplementedError(
            "FrameCapturer.capture is not supported; use capture_camera or "
            "capture_frames_from_manifest"
        )

    @staticmethod
    def _validate_frame(path: Path) -> tuple[int, int]:
        if Image is None:
            raise RuntimeError("Pillow is required to validate captured frames")
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"captured frame is missing or empty: {path.name}")
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, ValueError, ImportError) as exc:
            raise ValueError(f"captured frame is not a valid image: {path.name}") from exc
        if width <= 0 or height <= 0:
            raise ValueError(f"captured frame has invalid dimensions: {path.name}")
        return width, height

    @classmethod
    def _validate_burst(cls, frame_paths: list[Path], frame_count: int) -> tuple[int, int]:
        if len(frame_paths) != frame_count:
            raise ValueError(
                f"expected {frame_count} frames but decoded {len(frame_paths)}"
            )
        dimensions = [cls._validate_frame(path) for path in frame_paths]
        if len(set(dimensions)) != 1:
            raise ValueError("captured frames have inconsistent dimensions")
        return dimensions[0]

    @staticmethod
    def _base_result(camera: dict, stream_url: str | None, sample_fps: float | None, warmup_seconds: float) -> dict:
        return {
            "cam_id": camera.get("cam_id", "unknown"),
            "name": camera.get("name"),
            "district": camera.get("district"),
            "sub_district": camera.get("sub_district"),
            "stream_url": stream_url,
            "returncode": None,
            "frame_paths": [],
            "stdout": "",
            "stderr": "",
            "sample_fps": sample_fps,
            "warmup_seconds": warmup_seconds,
            "status": "failed",
            "health": {"status": "failed", "usable": False},
            "error": None,
            "decoded_frame_count": 0,
        }

    def capture_camera(
        self,
        camera: dict,
        frame_count: int = 3,
        ffmpeg_path: list[str] | None = None,
        burst_fps: float | None = None,
        warmup_seconds: float = 0.0,
    ) -> dict:
        """Capture frames for a single camera into the configured output directory."""
        if frame_count <= 0:
            raise ValueError("frame_count must be greater than zero")
        if burst_fps is not None and (
            not math.isfinite(float(burst_fps)) or float(burst_fps) <= 0
        ):
            raise ValueError("burst_fps must be finite and greater than zero")
        if not math.isfinite(float(warmup_seconds)) or float(warmup_seconds) < 0:
            raise ValueError("warmup_seconds must be finite and non-negative")

        stream_url = select_hls_url(camera.get("stream_urls"))
        sample_fps = burst_fps if frame_count > 1 else None
        result = self._base_result(camera, stream_url, sample_fps, warmup_seconds)
        if not stream_url:
            result["status"] = "unsupported"
            result["error"] = "no supported HLS stream URL"
            return result

        output_root = self.output_dir
        output_root.mkdir(parents=True, exist_ok=True)
        camera_output_dir = output_root / f"cam_{camera['cam_id']}"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        staging_dir = camera_output_dir / f".capture-{uuid.uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=False)
        frame_pattern = staging_dir / "frame_%03d.jpg"

        runner = self.ffmpeg_runner
        try:
            if ffmpeg_path is not None:
                if not ffmpeg_path:
                    raise ValueError("ffmpeg_path must not be empty")
                completed = subprocess.run(
                    [
                        *ffmpeg_path,
                        "-y", "-hide_banner", "-loglevel", "error",
                        *(["-ss", str(warmup_seconds)] if warmup_seconds > 0 else []),
                        "-i", stream_url,
                        *(["-vf", f"fps={sample_fps:g}"] if sample_fps is not None else []),
                        "-frames:v", str(frame_count), str(frame_pattern),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            else:
                completed = runner.capture_frames(
                    stream_url, frame_pattern, frame_count=frame_count,
                    sample_fps=sample_fps, warmup_seconds=warmup_seconds,
                )
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
            result["error"] = str(exc)
            result["status"] = "failed"
            for path in staging_dir.glob("*"):
                if path.is_file():
                    path.unlink()
            staging_dir.rmdir()
            return result

        result.update({
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        staged_frames = sorted(staging_dir.glob("frame_*.jpg"))
        result["decoded_frame_count"] = len(staged_frames)
        try:
            if completed.returncode != 0:
                raise RuntimeError(f"ffmpeg exited with return code {completed.returncode}")
            self._validate_burst(staged_frames, frame_count)
        except (OSError, RuntimeError, ValueError) as exc:
            result["error"] = str(exc)
            result["status"] = "partial" if staged_frames else "failed"
            for path in staged_frames:
                path.unlink(missing_ok=True)
            staging_dir.rmdir()
            return result

        for existing_frame in camera_output_dir.glob("frame_*.jpg"):
            existing_frame.unlink()
        published_paths: list[Path] = []
        for staged_frame in staged_frames:
            target = camera_output_dir / staged_frame.name
            staged_frame.replace(target)
            published_paths.append(target)
        staging_dir.rmdir()
        result["frame_paths"] = [str(path) for path in published_paths]
        result["status"] = "complete"
        result["health"] = {"status": "ok", "usable": True}
        return result

    def capture_frames_from_manifest(
        self,
        manifest: dict,
        frame_count: int = 3,
        ffmpeg_path: list[str] | None = None,
        burst_fps: float | None = 1.0,
        warmup_seconds: float = 0.0,
    ) -> list[dict]:
        """Capture frames from a feed manifest into the configured output directory."""
        results = []
        for camera in manifest.get("cameras", []):
            results.append(
                self.capture_camera(
                    camera,
                    frame_count=frame_count,
                    ffmpeg_path=ffmpeg_path,
                    burst_fps=burst_fps,
                    warmup_seconds=warmup_seconds,
                )
            )

        return results

    def capture_frames_loop(self, index_url: str, output_root: str | Path | None = None, frame_count: int = 3, interval_seconds: float = 5.0, max_cycles: int | None = None, ffmpeg_path: list[str] | None = None, burst_fps: float | None = 1.0, warmup_seconds: float = 0.0) -> list[dict]:
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
            results = self.capture_frames_from_manifest(
                manifest,
                frame_count=frame_count,
                ffmpeg_path=ffmpeg_path,
                burst_fps=burst_fps,
                warmup_seconds=warmup_seconds,
            )
            all_results.extend(results)
            cycle += 1
            if max_cycles is not None and cycle >= max_cycles:
                break
            time.sleep(interval_seconds)

        return all_results
