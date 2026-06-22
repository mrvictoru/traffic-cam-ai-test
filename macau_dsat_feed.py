from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.ingestion.dsat_client import DEFAULT_INDEX_URL, DSATClient, extract_camera_entries, extract_stream_urls


def fetch_text(url: str) -> str:
    client = DSATClient(index_url=url)
    return client._fetch_text(url)


def build_feed_manifest(index_url: str = DEFAULT_INDEX_URL, fetcher=None) -> dict:
    client = DSATClient(index_url=index_url, fetcher=fetcher)
    return client.build_manifest()


def build_feed_snapshot(index_url: str = DEFAULT_INDEX_URL, fetcher=None) -> dict:
    return build_feed_manifest(index_url=index_url, fetcher=fetcher)


def capture_frames_from_manifest(manifest: dict, output_root: str | Path | None = None, frame_count: int = 3, ffmpeg_path: list[str] | None = None) -> list[dict]:
    capturer = FrameCapturer(output_dir=output_root)
    return capturer.capture_frames_from_manifest(manifest, frame_count=frame_count, ffmpeg_path=ffmpeg_path)


def capture_frames_loop(index_url: str = DEFAULT_INDEX_URL, output_root: str | Path = "frames", frame_count: int = 3, interval_seconds: float = 5.0, max_cycles: int | None = None, ffmpeg_path: list[str] | None = None) -> list[dict]:
    capturer = FrameCapturer(output_dir=output_root)
    return capturer.capture_frames_loop(index_url=index_url, output_root=output_root, frame_count=frame_count, interval_seconds=interval_seconds, max_cycles=max_cycles, ffmpeg_path=ffmpeg_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the Macau DSAT realtime traffic camera feed index and resolve live stream URLs.")
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL, help="DSAT realtime index page URL.")
    parser.add_argument("--limit", type=int, default=None, help="Only print the first N cameras.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    parser.add_argument("--manifest", action="store_true", help="Write a manifest of discovered cameras and stream URLs.")
    parser.add_argument("--capture-frames", action="store_true", help="Capture frames from the discovered manifest into an output directory.")
    parser.add_argument("--capture-loop", action="store_true", help="Continuously capture frames from the discovered manifest until stopped.")
    parser.add_argument("--output-dir", default="frames", help="Directory for captured frames when --capture-frames or --capture-loop is used.")
    parser.add_argument("--frame-count", type=int, default=3, help="Number of frames to capture per camera when --capture-frames or --capture-loop is used.")
    parser.add_argument("--capture-interval", type=float, default=5.0, help="Delay in seconds between capture cycles when --capture-loop is used.")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum number of capture cycles when --capture-loop is used.")
    args = parser.parse_args()

    snapshot = build_feed_snapshot(index_url=args.index_url)
    if args.limit is not None:
        snapshot["cameras"] = snapshot["cameras"][: args.limit]
        snapshot["camera_count"] = len(snapshot["cameras"])

    if args.manifest:
        snapshot = build_feed_manifest(index_url=args.index_url)
        if args.limit is not None:
            snapshot["cameras"] = snapshot["cameras"][: args.limit]
            snapshot["camera_count"] = len(snapshot["cameras"])

    if args.capture_frames:
        manifest = snapshot if args.manifest else build_feed_manifest(index_url=args.index_url)
        if args.limit is not None:
            manifest["cameras"] = manifest["cameras"][: args.limit]
            manifest["camera_count"] = len(manifest["cameras"])
        capture_results = capture_frames_from_manifest(manifest, output_root=args.output_dir, frame_count=args.frame_count)
        snapshot = {"manifest": manifest, "capture_results": capture_results}

    if args.capture_loop:
        capture_results = capture_frames_loop(index_url=args.index_url, output_root=args.output_dir, frame_count=args.frame_count, interval_seconds=args.capture_interval, max_cycles=args.max_cycles)
        snapshot = {"capture_results": capture_results}

    dump_args = {"ensure_ascii": False}
    if args.pretty:
        dump_args["indent"] = 2
    print(json.dumps(snapshot, **dump_args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
