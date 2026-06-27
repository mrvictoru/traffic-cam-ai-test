from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from trafficcam.analysis.trends import TrendAnalyzer
from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.config import settings
from trafficcam.ingestion.dsat_client import DEFAULT_INDEX_URL, DSATClient
from trafficcam.storage.json_store import JsonStore
from trafficcam.vision import ZeroShotDetector, SceneClassifier, SimpleTracker
from trafficcam.vision.roi import filter_detections_to_roi, image_size, load_camera_rois

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

def _analyze_burst(
    frame_paths: list[str],
    camera_id: str,
    capture_result: dict[str, Any],
    roi_polygon: list[list[float]] | None = None,
) -> dict[str, Any]:
    """Analyze a burst of frames using zero-shot detection + tracking + scene classification."""
    detector = ZeroShotDetector()
    scene_classifier = SceneClassifier()
    tracker = SimpleTracker()

    per_frame_results: list[dict[str, Any]] = []
    all_detections: list[dict[str, Any]] = []
    scene_info: dict[str, Any] = {}

    for idx, frame_path in enumerate(frame_paths):
        detection = detector.analyze(frame_path)
        if roi_polygon:
            width, height = image_size(frame_path)
            filtered_detections = filter_detections_to_roi(
                detection.get("detections", []),
                roi_polygon,
                width,
                height,
            )
            detection["detections"] = filtered_detections
            detection["vehicle_count"] = len(filtered_detections)
            detection["confidence"] = round(
                (
                    sum(d["confidence"] for d in filtered_detections)
                    / len(filtered_detections)
                )
                if filtered_detections
                else 0.0,
                4,
            )
        tracks = tracker.update(detection.get("detections", []))
        LOGGER.info(
            "Frame %d: %d detections (density=%s, confidence=%.3f, tracks=%d)",
            idx,
            detection.get("vehicle_count", 0),
            detection.get("label", "unknown"),
            detection.get("confidence", 0.0),
            len(tracks),
        )
        per_frame_results.append(
            {
                "frame_idx": idx,
                "image_path": frame_path,
                "vehicle_count": detection.get("vehicle_count", 0),
                "density": detection.get("label", "unknown"),
                "confidence": detection.get("confidence", 0.0),
                "active_tracks": len(tracks),
            }
        )
        all_detections.extend(detection.get("detections", []))

    # Scene classification on the middle frame (most representative)
    if frame_paths:
        middle_frame = frame_paths[len(frame_paths) // 2]
        scene_info = scene_classifier.classify(middle_frame)

    # Aggregate across burst
    total_vehicles = sum(r["vehicle_count"] for r in per_frame_results)
    mean_confidence = (
        sum(r["confidence"] for r in per_frame_results) / len(per_frame_results)
        if per_frame_results else 0.0
    )
    density_counts: dict[str, int] = {}
    for r in per_frame_results:
        density_counts[r["density"]] = density_counts.get(r["density"], 0) + 1
    dominant_density = max(density_counts, key=density_counts.get) if density_counts else "unknown"

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "camera_id": camera_id,
        "captured_at": captured_at,
        "label": dominant_density,
        "details": {
            "density": dominant_density,
            "vehicle_count": total_vehicles,
            "mean_confidence": round(mean_confidence, 4),
            "active_tracks": tracker.active_count,
            "scene": scene_info.get("scene", "unknown"),
            "lighting": scene_info.get("lighting", "unknown"),
            "visibility": scene_info.get("visibility", "unknown"),
            "quality_flag": scene_info.get("quality_flag", "unknown"),
            "frame_count": len(frame_paths),
            "per_frame": per_frame_results,
            "capture_result": {
                "cam_id": camera_id,
                "name": capture_result.get("name"),
                "district": capture_result.get("district"),
                "stream_url": capture_result.get("stream_url"),
                "sample_fps": capture_result.get("sample_fps"),
                "warmup_seconds": capture_result.get("warmup_seconds"),
                "roi_applied": bool(roi_polygon),
            },
        },
    }


def _run_single_cycle(
    cameras: list[dict[str, Any]],
    data_root: Path,
    frame_count: int,
    store: JsonStore,
    capturer: FrameCapturer,
    burst_fps: float | None,
    warmup_seconds: float,
    roi_registry: dict[str, list[list[float]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one capture-and-analyze cycle. Returns capture_results and analysis_records."""
    capture_results: list[dict[str, Any]] = []
    analysis_records: list[dict[str, Any]] = []

    for camera in cameras:
        camera_id = str(camera.get("cam_id") or camera.get("camera_id") or "unknown")
        roi_polygon = roi_registry.get(camera_id)

        capture = capturer.capture_camera(
            camera,
            frame_count=frame_count,
            burst_fps=burst_fps,
            warmup_seconds=warmup_seconds,
        )
        capture_results.append(capture)

        if not capture["frame_paths"]:
            continue

        analysis = _analyze_burst(
            capture["frame_paths"],
            camera_id,
            capture,
            roi_polygon=roi_polygon,
        )
        analysis_records.append(analysis)

        # Persist analysis record
        ts = analysis["captured_at"].replace(":", "").replace("-", "").replace(".", "")
        record_path = f"analyses/{camera_id}/{ts}.json"
        store.save_json(record_path, analysis)

    return capture_results, analysis_records


def run_pipeline(
    manifest_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    frame_count: int = 1,
    limit: int | None = None,
    interval: float = 0.0,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    """Run the end-to-end pipeline: discover, capture, analyze, persist, detect trends."""
    manifest_path = Path(manifest_file or "data/manifest.json")
    output_root = Path(output_dir or "output/e2e")
    data_root = Path(data_dir or "data")
    output_root.mkdir(parents=True, exist_ok=True)
    data_root.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        try:
            manifest = DSATClient(index_url=DEFAULT_INDEX_URL).build_manifest(limit=limit)
        except Exception as exc:
            manifest = {
                "source_url": DEFAULT_INDEX_URL,
                "camera_count": 0,
                "cameras": [],
                "fetch_error": str(exc),
            }

    cameras = manifest.get("cameras", [])
    if limit is not None:
        cameras = cameras[:limit]

    store = JsonStore(data_root)
    capturer = FrameCapturer(output_dir=output_root)
    roi_registry = (
        load_camera_rois(settings.roi_config_path)
        if settings.roi_filter_enabled
        else {}
    )
    all_capture_results: list[dict[str, Any]] = []
    all_analysis_records: list[dict[str, Any]] = []

    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        capture_results, analysis_records = _run_single_cycle(
            cameras,
            data_root,
            frame_count,
            store,
            capturer,
            burst_fps=settings.capture_burst_fps,
            warmup_seconds=settings.capture_warmup_seconds,
            roi_registry=roi_registry,
        )
        all_capture_results.extend(capture_results)
        all_analysis_records.extend(analysis_records)

        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            break

        if interval > 0:
            time.sleep(interval)

    # Trend analysis: run incident detection for each camera
    analyzer = TrendAnalyzer(store)
    camera_ids = sorted(
        {str(c.get("cam_id") or c.get("camera_id") or "unknown") for c in cameras}
    )
    incident_summaries: dict[str, Any] = {}
    for camera_id in camera_ids:
        incidents = analyzer.detect_incidents(camera_id, persist=True)
        incident_summaries[camera_id] = len(incidents)

    return {
        "analysis_count": len(all_analysis_records),
        "camera_ids": camera_ids,
        "output_dir": str(output_root),
        "data_dir": str(data_root),
        "capture_results": all_capture_results,
        "incident_summaries": incident_summaries,
        "cycles_completed": cycle,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the end-to-end traffic analytics pipeline with AI vision"
    )
    parser.add_argument("--manifest-file", default="data/manifest.json")
    parser.add_argument("--output-dir", default="output/e2e")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--frame-count", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--interval", type=float, default=0.0, help="Seconds between capture cycles (0 = single-shot)")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum capture cycles (None = infinite)")
    args = parser.parse_args()

    result = run_pipeline(
        manifest_file=args.manifest_file,
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        frame_count=args.frame_count,
        limit=args.limit,
        interval=args.interval,
        max_cycles=args.max_cycles,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
