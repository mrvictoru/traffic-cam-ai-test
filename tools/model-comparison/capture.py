"""Capture time-spaced, matched clips from selected DSAT camera feeds."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path("/app") / "src"))

from trafficcam.ingestion.dsat_client import (  # noqa: E402
    DEFAULT_INDEX_URL,
    DSATClient,
    _follow_reload_page,
    extract_camera_entries,
    extract_stream_urls,
)
from trafficcam.ingestion.stream_urls import select_hls_url  # noqa: E402


CAMERA_IDS = ("49", "51", "58", "109")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _discover_selected_cameras() -> list[dict[str, Any]]:
    client = DSATClient()
    index_html = client.fetcher(DEFAULT_INDEX_URL)
    entries = {
        camera.cam_id: camera
        for camera in extract_camera_entries(index_html, DEFAULT_INDEX_URL)
        if camera.cam_id in CAMERA_IDS
    }
    missing = set(CAMERA_IDS) - entries.keys()
    if missing:
        raise RuntimeError(f"DSAT no longer lists requested camera IDs: {sorted(missing)}")

    cameras = []
    for camera_id in CAMERA_IDS:
        entry = entries[camera_id]
        detail_url = entry.detail_url
        detail_html = client.fetcher(detail_url)
        stream_urls = extract_stream_urls(detail_html, detail_url)
        if not stream_urls:
            redirect_url = _follow_reload_page(detail_html, detail_url)
            if redirect_url and redirect_url != detail_url:
                detail_html = client.fetcher(redirect_url)
                stream_urls = extract_stream_urls(detail_html, redirect_url)
        stream_url = select_hls_url(stream_urls)
        if not stream_url:
            raise RuntimeError(f"No HLS feed was discovered for camera {camera_id}")
        cameras.append(
            {
                "cam_id": camera_id,
                "name": entry.name,
                "district": entry.district,
                "sub_district": entry.sub_district,
                "stream_url": stream_url,
            }
        )
    return cameras


def _probe(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,avg_frame_rate,nb_frames",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise ValueError(f"no video stream in {path.name}")
    stream = streams[0]
    stream["duration_seconds"] = float((payload.get("format") or {}).get("duration") or 0)
    return stream


def _capture_one(
    camera: dict[str, Any],
    output_path: Path,
    duration_seconds: int,
    fps: int,
) -> dict[str, Any]:
    started_at = _utc_now()
    start = time.monotonic()
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        camera["stream_url"],
        "-t",
        str(duration_seconds),
        "-vf",
        f"fps={fps}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=duration_seconds + 180,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {completed.returncode}: {completed.stderr[-1500:]}")
        media = _probe(output_path)
        if media["duration_seconds"] < duration_seconds - 5:
            raise RuntimeError(
                f"short capture: {media['duration_seconds']:.1f}s of "
                f"{duration_seconds}s requested"
            )
        return {
            "camera_id": camera["cam_id"],
            "name": camera.get("name"),
            "district": camera.get("district"),
            "sub_district": camera.get("sub_district"),
            "path": str(output_path),
            "status": "complete",
            "requested_duration_seconds": duration_seconds,
            "fps": fps,
            "started_at_utc": started_at,
            "elapsed_wall_seconds": round(time.monotonic() - start, 3),
            "media": media,
        }
    except Exception as exc:
        return {
            "camera_id": camera["cam_id"],
            "name": camera.get("name"),
            "path": str(output_path),
            "status": "failed",
            "requested_duration_seconds": duration_seconds,
            "fps": fps,
            "started_at_utc": started_at,
            "elapsed_wall_seconds": round(time.monotonic() - start, 3),
            "error": str(exc),
        }


def _capture_round(
    cameras: list[dict[str, Any]],
    output_dir: Path,
    round_number: int,
    duration_seconds: int,
    fps: int,
) -> list[dict[str, Any]]:
    round_dir = output_dir / f"round-{round_number:02d}"
    round_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[concurrent.futures.Future[dict[str, Any]], dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cameras)) as executor:
        for camera in cameras:
            filename = f"cam-{camera['cam_id']}-{duration_seconds}s.mp4"
            jobs[
                executor.submit(
                    _capture_one,
                    camera,
                    round_dir / filename,
                    duration_seconds,
                    fps,
                )
            ] = camera
        return [future.result() for future in concurrent.futures.as_completed(jobs)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--fps", type=int, default=5)
    args = parser.parse_args()
    if args.rounds <= 0 or args.interval_seconds <= 0 or args.duration_seconds <= 0 or args.fps <= 0:
        parser.error("rounds, interval-seconds, duration-seconds, and fps must be positive")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cameras = _discover_selected_cameras()
    camera_metadata = [{key: value for key, value in camera.items() if key != "stream_url"} for camera in cameras]
    manifest_path = output_dir / "capture-manifest.json"
    payload: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": _utc_now(),
        "camera_ids": list(CAMERA_IDS),
        "round_interval_seconds": args.interval_seconds,
        "requested_duration_seconds": args.duration_seconds,
        "target_fps": args.fps,
        "cameras": camera_metadata,
        "rounds": [],
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Discovered current HLS streams for cameras {', '.join(CAMERA_IDS)}.")
    print(f"Saving source clips and run metadata under {output_dir}.")
    first_round_start = time.monotonic()
    failed = False
    for round_number in range(1, args.rounds + 1):
        target_start = first_round_start + (round_number - 1) * args.interval_seconds
        delay = target_start - time.monotonic()
        if delay > 0:
            target_utc = datetime.now(timezone.utc) + timedelta(seconds=delay)
            print(f"Round {round_number} starts at {target_utc.isoformat()}; waiting {delay:.0f}s.")
            time.sleep(delay)
        started_at = _utc_now()
        results = _capture_round(
            cameras,
            output_dir,
            round_number,
            args.duration_seconds,
            args.fps,
        )
        for result in results:
            if result["status"] != "complete":
                failed = True
            print(
                f"Round {round_number} camera {result['camera_id']}: "
                f"{result['status']} ({result['elapsed_wall_seconds']:.1f}s wall)"
            )
        payload["rounds"].append(
            {"round": round_number, "started_at_utc": started_at, "captures": results}
        )
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Capture manifest: {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
