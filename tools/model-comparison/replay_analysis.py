"""Feed saved detections from both models through the shared analysis burst path."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

REPOSITORY = Path("/app")
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(REPOSITORY / "src"))

from scripts.run_e2e_pipeline import _analyze_burst  # noqa: E402
from trafficcam.config import settings  # noqa: E402
from trafficcam.vision import SceneClassifier  # noqa: E402
from trafficcam.vision.roi import load_camera_flow_lines, load_camera_rois  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)


class RecordedDetector:
    def __init__(self, payload: dict[str, Any], backend: str, model: str):
        self.frames = payload["frames"]
        self.backend = backend
        self.model_name = model
        self._index = 0

    def analyze(self, image_path: str, camera_id: str | None = None) -> dict[str, Any]:
        if self._index >= len(self.frames):
            raise RuntimeError(f"replay exhausted detections for camera {camera_id}")
        recorded = self.frames[self._index]
        self._index += 1
        if Path(image_path).name != Path(recorded["frame_path"]).name:
            raise RuntimeError(
                f"frame/detection sequence mismatch at index {self._index - 1}: "
                f"{image_path} vs {recorded['frame_path']}"
            )
        detections = recorded.get("vehicle_detections")
        if detections is None:
            detections = [
                detection
                for detection in recorded.get("detections", [])
                if detection.get("label", "").lower()
                in {"car", "truck", "bus", "motorcycle", "bicycle", "van", "taxi", "suv"}
            ]
        confidence = (
            sum(float(detection["confidence"]) for detection in detections) / len(detections)
            if detections
            else 0.0
        )
        return {
            "image_path": image_path,
            "label": "light",
            "confidence": confidence,
            "detections": detections,
            "vehicle_count": len(detections),
            "backend": self.backend,
            "model_name": self.model_name,
        }


def run_replay(run_dir: Path, detector_backend: str, duration: int) -> list[dict[str, Any]]:
    detection_root = run_dir / "detections" / detector_backend
    frame_root = run_dir / "frames"
    if not detection_root.exists():
        raise RuntimeError(f"missing detections for backend {detector_backend}: {detection_root}")
    rois = load_camera_rois(settings.roi_config_path)
    flow_lines = load_camera_flow_lines(settings.flow_line_config_path)
    summaries = []
    for detections_path in sorted(detection_root.glob(f"round-*/cam-*-{duration}s.json")):
        payload = json.loads(detections_path.read_text(encoding="utf-8"))
        round_name = detections_path.parent.name
        camera_id = str(payload["camera_id"])
        paths = sorted((frame_root / round_name / f"cam-{camera_id}").glob("frame_*.jpg"))
        if len(paths) < int(payload["frame_count"]):
            raise RuntimeError(
                f"{detections_path} references {payload['frame_count']} frames but only "
                f"{len(paths)} JPEGs were decoded"
            )
        paths = paths[: int(payload["frame_count"])]
        detector = RecordedDetector(payload, detector_backend, str(payload["model"]))
        capture_result = {
            "status": "complete",
            "frame_paths": [str(path) for path in paths],
            "sample_fps": 5.0,
            "warmup_seconds": 0.0,
            "decoded_frame_count": len(paths),
        }
        analysis_started = time.perf_counter()
        analysis = _analyze_burst(
            frame_paths=[str(path) for path in paths],
            camera_id=camera_id,
            capture_result=capture_result,
            roi_polygon=rois.get(camera_id),
            flow_line=flow_lines.get(camera_id),
            data_dir=run_dir,
            detector=detector,
            scene_classifier=SceneClassifier(use_zero_shot=False),
        )
        analysis_seconds = time.perf_counter() - analysis_started
        if detector._index != len(paths):
            raise RuntimeError(f"analysis consumed {detector._index} of {len(paths)} frames")
        result = {
            "schema_version": 1,
            "backend": detector_backend,
            "model": payload["model"],
            "camera_id": camera_id,
            "round": round_name,
            "duration_seconds": duration,
            "frame_count": len(paths),
            "detection_inference": {
                key: value
                for key, value in payload.items()
                if key
                in {
                    "first_call_ms_including_lazy_load",
                    "first_detection_after_play_ms",
                    "warm_per_frame",
                    "nvinfer_stage",
                    "all_detector_calls",
                    "mean_detector_call_ms",
                    "processing_wall_seconds_including_decode",
                    "processing_wall_seconds_including_decode_and_jpeg_write",
                    "effective_frames_per_second",
                    "gpu_device_memory_sampled_peak_mib_including_other_processes",
                    "gpu_memory_sample_count",
                }
            },
            "analysis_pipeline_wall_seconds_using_saved_detections": round(analysis_seconds, 3),
            "analysis": analysis,
        }
        output = run_dir / "analysis" / detector_backend / round_name / f"cam-{camera_id}-{duration}s.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
        details = analysis["details"]
        print(
            f"{detector_backend} {round_name} camera {camera_id} {duration}s: "
            f"mean vehicles {details['vehicle_count']}, congestion {details['congestion_score']}, "
            f"crossings {details['line_crossings']}, "
            f"analysis replay {analysis_seconds:.2f}s"
        )
        summaries.append(result)
    if not summaries:
        raise RuntimeError(f"no {duration}s detection files for backend {detector_backend}")
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, choices=(30, 120), default=120)
    parser.add_argument("--backend", choices=("yolo", "trafficcamnet", "both"), default="both")
    args = parser.parse_args()
    backends = ("yolo", "trafficcamnet") if args.backend == "both" else (args.backend,)
    for backend in backends:
        run_replay(args.run_dir.resolve(), backend, args.duration_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
