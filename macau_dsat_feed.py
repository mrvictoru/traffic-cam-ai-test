from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.cli import main as trafficcam_main
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


def _translate_legacy_args(argv: Sequence[str] | None = None) -> list[str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--capture-frames", action="store_true")
    parser.add_argument("--capture-loop", action="store_true")
    parser.add_argument("--output-dir", default="frames")
    parser.add_argument("--frame-count", type=int, default=3)
    parser.add_argument("--capture-interval", type=float, default=5.0)
    parser.add_argument("--max-cycles", type=int, default=None)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    translated = ["discover", "--index-url", args.index_url]
    if args.limit is not None:
        translated.extend(["--limit", str(args.limit)])
    if args.pretty:
        translated.append("--pretty")

    if args.capture_loop:
        translated = [
            "capture-loop",
            "--index-url",
            args.index_url,
            "--output-dir",
            args.output_dir,
            "--frame-count",
            str(args.frame_count),
            "--capture-interval",
            str(args.capture_interval),
        ]
        if args.max_cycles is not None:
            translated.extend(["--max-cycles", str(args.max_cycles)])
        if args.pretty:
            translated.append("--pretty")
        return translated

    if args.capture_frames:
        translated = [
            "capture-frames",
            "--index-url",
            args.index_url,
            "--output-dir",
            args.output_dir,
            "--frame-count",
            str(args.frame_count),
        ]
        if args.limit is not None:
            translated.extend(["--limit", str(args.limit)])
        if args.pretty:
            translated.append("--pretty")
        return translated

    return translated


def main(argv: Sequence[str] | None = None) -> int:
    return trafficcam_main(_translate_legacy_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
