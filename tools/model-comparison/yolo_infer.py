"""Run the configured project YOLO detector on captured comparison clips."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import torch

sys.path.insert(0, str(Path("/app") / "src"))

from trafficcam.config import settings  # noqa: E402
from trafficcam.vision import ZeroShotDetector  # noqa: E402


class GpuMemorySampler:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self.samples_mib: list[int] = []

    def start(self) -> None:
        self._process = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                "--loop-ms=250",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        def sample() -> None:
            assert self._process is not None and self._process.stdout is not None
            for line in self._process.stdout:
                try:
                    self.samples_mib.append(int(line.strip()))
                except ValueError:
                    continue

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=3)
        if self._thread is not None:
            self._thread.join(timeout=3)


def _summarize(samples: list[float]) -> dict[str, float | None]:
    if not samples:
        return {"median_ms": None, "p95_ms": None}
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def _run_clip(
    clip: Path,
    run_dir: Path,
    detector: ZeroShotDetector,
    duration_seconds: int,
) -> dict[str, Any]:
    round_name = clip.parent.name
    camera_id = clip.name.split("-")[1]
    capture = cv2.VideoCapture(str(clip))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open captured clip {clip}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_limit = min(
        int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
        round(source_fps * duration_seconds),
    )

    frame_dir = run_dir / "frames" / round_name / f"cam-{camera_id}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    first_call_ms: float | None = None
    frame_index = 0
    start = time.perf_counter()
    memory_sampler = GpuMemorySampler()
    memory_sampler.start()
    try:
        while frame_index < frame_limit:
            ok, image = capture.read()
            if not ok:
                break
            frame_path = frame_dir / f"frame_{frame_index + 1:06d}.jpg"
            if not cv2.imwrite(str(frame_path), image):
                raise RuntimeError(f"OpenCV failed to write decoded frame {frame_path}")
            inference_start = time.perf_counter()
            result = detector.analyze(str(frame_path), camera_id=camera_id)
            latency_ms = (time.perf_counter() - inference_start) * 1000
            if first_call_ms is None:
                first_call_ms = latency_ms
            else:
                latencies_ms.append(latency_ms)
            frames.append(
                {
                    "frame_index": frame_index,
                    "frame_path": str(frame_path.relative_to(run_dir)),
                    "detections": result["detections"],
                    "vehicle_count": result["vehicle_count"],
                    "inference_ms": round(latency_ms, 3),
                }
            )
            frame_index += 1
    finally:
        capture.release()
        memory_sampler.stop()
    elapsed = time.perf_counter() - start
    output_path = (
        run_dir
        / "detections"
        / "yolo"
        / round_name
        / f"cam-{camera_id}-{duration_seconds}s.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    inference_samples = [frame["inference_ms"] for frame in frames]
    payload = {
        "schema_version": 1,
        "model": detector.model_name,
        "backend": detector.backend,
        "device": detector.device,
        "confidence_threshold": settings.vision_confidence_threshold,
        "camera_id": camera_id,
        "round": round_name,
        "source_clip": str(clip.relative_to(run_dir)),
        "source_fps": source_fps,
        "requested_duration_seconds": duration_seconds,
        "frame_count": frame_index,
        "first_call_ms_including_lazy_load": round(first_call_ms or 0, 3),
        "warm_per_frame": _summarize(latencies_ms),
        "all_detector_calls": _summarize(inference_samples),
        "mean_detector_call_ms": round(statistics.mean(inference_samples), 3)
        if inference_samples
        else None,
        "processing_wall_seconds_including_decode_and_jpeg_write": round(elapsed, 3),
        "effective_frames_per_second": round(frame_index / elapsed, 3) if elapsed else None,
        "gpu_device_memory_sampled_peak_mib_including_other_processes": max(
            memory_sampler.samples_mib, default=None
        ),
        "gpu_memory_sample_count": len(memory_sampler.samples_mib),
        "frames": frames,
    }
    output_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(
        f"YOLO {round_name} camera {camera_id}: {frame_index} frames, "
        f"{elapsed:.1f}s end-to-end, first call {first_call_ms or 0:.1f}ms, "
        f"warm median {_summarize(latencies_ms)['median_ms']}ms"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=int, choices=(30, 120), default=120)
    parser.add_argument("--camera-id")
    parser.add_argument("--round")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    clips = sorted(run_dir.glob("round-*/cam-*-120s.mp4"))
    if args.camera_id:
        clips = [clip for clip in clips if clip.name.startswith(f"cam-{args.camera_id}-")]
    if args.round:
        clips = [clip for clip in clips if clip.parent.name == args.round]
    if not clips:
        parser.error(f"no captured 120-second clips found in {run_dir}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable in the YOLO benchmark container")
    if not settings.vision_device.startswith("cuda"):
        raise RuntimeError(f"expected a CUDA device, got {settings.vision_device!r}")
    detector = ZeroShotDetector(
        backend="yolo",
        model_name=settings.vision_yolo_model_name,
        device=settings.vision_device,
        confidence_threshold=settings.vision_confidence_threshold,
    )
    for clip in clips:
        _run_clip(clip, run_dir, detector, args.duration_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
