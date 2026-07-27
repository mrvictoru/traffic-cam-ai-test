"""Command line entry points for the traffic camera pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from trafficcam.config import settings
from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.ingestion.dsat_client import DEFAULT_INDEX_URL, DSATClient


def _write_json(path: str | Path, payload: dict[str, Any], pretty: bool = False) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None),
        encoding="utf-8",
    )


def _print_json(payload: dict[str, Any], pretty: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if pretty else None))


def build_parser() -> argparse.ArgumentParser:
    """Create a CLI parser for the supported prototype workflows."""
    parser = argparse.ArgumentParser(description="Traffic cam ingestion and analysis pipeline")
    subparsers = parser.add_subparsers(dest="command")

    discover = subparsers.add_parser("discover", help="Discover DSAT cameras and emit a manifest")
    discover.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    discover.add_argument("--limit", type=int, default=None)
    discover.add_argument("--manifest-file", default=None)
    discover.add_argument("--pretty", action="store_true")

    capture_frames = subparsers.add_parser(
        "capture-frames",
        help="Discover DSAT cameras and capture frames without analysis",
    )
    capture_frames.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    capture_frames.add_argument("--limit", type=int, default=None)
    capture_frames.add_argument("--output-dir", default="frames")
    capture_frames.add_argument("--frame-count", type=int, default=settings.frame_count)
    capture_frames.add_argument("--pretty", action="store_true")

    capture_loop = subparsers.add_parser(
        "capture-loop",
        help="Repeatedly discover DSAT cameras and capture frames without analysis",
    )
    capture_loop.add_argument("--index-url", default=DEFAULT_INDEX_URL)
    capture_loop.add_argument("--output-dir", default="frames")
    capture_loop.add_argument("--frame-count", type=int, default=settings.frame_count)
    capture_loop.add_argument("--capture-interval", type=float, default=5.0)
    capture_loop.add_argument("--max-cycles", type=int, default=None)
    capture_loop.add_argument("--pretty", action="store_true")

    run_once = subparsers.add_parser("run-once", help="Run one end-to-end capture and analysis cycle")
    run_once.add_argument("--manifest-file", default="data/manifest.json")
    run_once.add_argument("--output-dir", default="output/e2e")
    run_once.add_argument("--data-dir", default="data")
    run_once.add_argument("--frame-count", type=int, default=1)
    run_once.add_argument("--limit", type=int, default=None)
    run_once.add_argument("--pretty", action="store_true")

    run_loop = subparsers.add_parser("run-loop", help="Run repeated capture and analysis cycles")
    run_loop.add_argument("--manifest-file", default="data/manifest.json")
    run_loop.add_argument("--output-dir", default="output/e2e")
    run_loop.add_argument("--data-dir", default="data")
    run_loop.add_argument("--frame-count", type=int, default=1)
    run_loop.add_argument("--limit", type=int, default=None)
    run_loop.add_argument("--interval", type=float, default=settings.capture_interval_seconds)
    run_loop.add_argument("--max-cycles", type=int, default=settings.capture_max_cycles)
    run_loop.add_argument("--pretty", action="store_true")

    serve = subparsers.add_parser("serve", help="Run the FastAPI web/API server")
    serve.add_argument("--host", default=settings.api_host)
    serve.add_argument("--port", type=int, default=settings.api_port)
    serve.add_argument("--reload", action="store_true")

    return parser


def _dispatch_discover(args: argparse.Namespace) -> int:
    manifest = DSATClient(index_url=args.index_url).build_manifest(limit=args.limit)
    if args.manifest_file:
        _write_json(args.manifest_file, manifest, pretty=args.pretty)
    _print_json(manifest, pretty=args.pretty)
    return 0


def _dispatch_capture_frames(args: argparse.Namespace) -> int:
    manifest = DSATClient(index_url=args.index_url).build_manifest(limit=args.limit)
    capturer = FrameCapturer(output_dir=args.output_dir)
    results = capturer.capture_frames_from_manifest(manifest, frame_count=args.frame_count)
    _print_json({"manifest": manifest, "capture_results": results}, pretty=args.pretty)
    return 0


def _dispatch_capture_loop(args: argparse.Namespace) -> int:
    capturer = FrameCapturer(output_dir=args.output_dir)
    results = capturer.capture_frames_loop(
        index_url=args.index_url,
        output_root=args.output_dir,
        frame_count=args.frame_count,
        interval_seconds=args.capture_interval,
        max_cycles=args.max_cycles,
    )
    _print_json({"capture_results": results}, pretty=args.pretty)
    return 0


def _dispatch_run(args: argparse.Namespace, *, interval: float, max_cycles: int | None) -> int:
    from trafficcam.pipeline import run_pipeline

    result = run_pipeline(
        manifest_file=args.manifest_file,
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        frame_count=args.frame_count,
        limit=args.limit,
        interval=interval,
        max_cycles=max_cycles,
    )
    _print_json(result, pretty=args.pretty)
    return 0


def _dispatch_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("trafficcam.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args:
        raw_args = ["discover"]
    args = parser.parse_args(raw_args)

    if args.command == "discover":
        return _dispatch_discover(args)
    if args.command == "capture-frames":
        return _dispatch_capture_frames(args)
    if args.command == "capture-loop":
        return _dispatch_capture_loop(args)
    if args.command == "run-once":
        return _dispatch_run(args, interval=0.0, max_cycles=1)
    if args.command == "run-loop":
        return _dispatch_run(args, interval=args.interval, max_cycles=args.max_cycles)
    if args.command == "serve":
        return _dispatch_serve(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
