from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trafficcam.analysis.trends import TrendAnalyzer
from trafficcam.analysis.traffic_detector import TrafficDetector
from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.ingestion.dsat_client import DEFAULT_INDEX_URL, DSATClient
from trafficcam.storage.json_store import JsonStore


def _build_sample_records(camera_id: str, captured_at: datetime, count: int = 3) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(count):
        ts = captured_at + timedelta(minutes=index * 10)
        density = "moderate" if index < 2 else "heavy"
        flow_total = 600 + index * 120
        records.append(
            {
                "camera_id": camera_id,
                "captured_at": ts.isoformat().replace("+00:00", "Z"),
                "label": density,
                "details": {
                    "density": density,
                    "flow_rate_vph": {
                        "northbound": flow_total // 2,
                        "southbound": flow_total // 2,
                        "total": flow_total,
                    },
                },
            }
        )
    return records


def run_pipeline(
    manifest_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    frame_count: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run a live-ish end-to-end pipeline using a manifest, capture frames, and persist analyses."""
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
    detector = TrafficDetector()
    capture_results: list[dict[str, Any]] = []
    analysis_records: list[dict[str, Any]] = []

    for camera in cameras:
        camera_id = str(camera.get("cam_id") or camera.get("camera_id") or "unknown")
        camera_output_dir = output_root / f"cam_{camera_id}"
        camera_output_dir.mkdir(parents=True, exist_ok=True)

        stream_urls = camera.get("stream_urls") or []
        stream_url = next((url for url in stream_urls if str(url).lower().endswith(".m3u8")), None)
        if stream_url:
            frame_pattern = str(camera_output_dir / "frame_%03d.jpg")
            command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", stream_url, "-frames:v", str(frame_count), frame_pattern]
            completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
            frame_paths = sorted(camera_output_dir.glob("frame_*.jpg"))
            capture_results.append(
                {
                    "cam_id": camera_id,
                    "stream_url": stream_url,
                    "returncode": completed.returncode,
                    "frame_paths": [str(path) for path in frame_paths],
                }
            )
        else:
            capture_results.append({"cam_id": camera_id, "stream_url": None, "returncode": None, "frame_paths": []})
            continue

        for frame_path in sorted(camera_output_dir.glob("frame_*.jpg")):
            analysis = detector.analyze(str(frame_path))
            captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            record = {
                "camera_id": camera_id,
                "captured_at": captured_at,
                "label": analysis["label"],
                "details": {
                    "density": analysis["label"],
                    "image_path": str(frame_path),
                    "confidence": analysis.get("confidence"),
                    "capture_result": {
                        "cam_id": camera_id,
                        "stream_url": stream_url,
                    },
                },
            }
            analysis_records.append(record)
            record_path = f"analyses/{camera_id}/{captured_at.replace(':', '').replace('-', '').replace('.', '')}_{frame_path.name}.json"
            store.save_json(record_path, record)

    analyzer = TrendAnalyzer(store)
    camera_ids = sorted({str(camera.get("cam_id") or camera.get("camera_id") or "unknown") for camera in cameras})
    analysis_count = len(analysis_records)
    for camera_id in camera_ids:
        analyzer.detect_incidents(camera_id, persist=True)

    return {
        "analysis_count": analysis_count,
        "camera_ids": camera_ids,
        "output_dir": str(output_root),
        "data_dir": str(data_root),
        "capture_results": capture_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight end-to-end traffic analytics pipeline")
    parser.add_argument("--manifest-file", default="data/manifest.json")
    parser.add_argument("--output-dir", default="output/e2e")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--frame-count", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    result = run_pipeline(
        manifest_file=args.manifest_file,
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        frame_count=args.frame_count,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
