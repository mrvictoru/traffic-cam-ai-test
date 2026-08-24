"""Command line entry points for the traffic camera pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from trafficcam.calibration import calibrate, summarize_calibration_coverage
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


def _load_json(path: str | Path) -> Any:
    target = Path(path)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_manifest_camera_ids(path: str | Path) -> list[str]:
    payload = _load_json(path)
    cameras = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(cameras, list):
        return []
    return [str(entry.get("cam_id")) for entry in cameras if isinstance(entry, dict) and entry.get("cam_id")]


def _load_manifest_cameras(path: str | Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    cameras = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(cameras, list):
        return []
    return [entry for entry in cameras if isinstance(entry, dict) and entry.get("cam_id")]


def _load_coordinate_ids(path: str | Path) -> set[str]:
    payload = _load_json(path)
    cameras = payload.get("cameras") if isinstance(payload, dict) else None
    if not isinstance(cameras, dict):
        return set()
    return {str(camera_id) for camera_id, entry in cameras.items() if isinstance(entry, dict)}


def _load_threshold_ids(path: str | Path) -> set[str]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return set()
    entries = payload.get("cameras") if isinstance(payload.get("cameras"), dict) else payload
    if not isinstance(entries, dict):
        return set()
    return {str(camera_id) for camera_id, entry in entries.items() if isinstance(entry, dict)}


def _load_plain_object_ids(path: str | Path) -> set[str]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        return set()
    return {str(camera_id) for camera_id, entry in payload.items() if isinstance(entry, (dict, list))}


def _camera_sort_key(camera_id: str) -> tuple[int, str]:
    try:
        return (0, f"{int(camera_id):08d}")
    except (TypeError, ValueError):
        return (1, str(camera_id))


def _build_config_audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest_cameras = _load_manifest_cameras(args.manifest_file)
    manifest_camera_ids = [str(entry.get("cam_id")) for entry in manifest_cameras]
    manifest_set = set(manifest_camera_ids)
    manifest_by_id = {str(entry.get("cam_id")): entry for entry in manifest_cameras}

    coordinate_ids = _load_coordinate_ids(args.coordinates_file)
    threshold_ids = _load_threshold_ids(args.thresholds_file)
    speed_calibration_ids = _load_threshold_ids(args.calibration_file)
    roi_ids = _load_plain_object_ids(args.rois_file)
    flow_line_ids = _load_plain_object_ids(args.flow_lines_file)

    missing_coordinates = sorted(manifest_set - coordinate_ids, key=_camera_sort_key)
    missing_thresholds = sorted(manifest_set - threshold_ids, key=_camera_sort_key)
    missing_speed_calibrations = sorted(manifest_set - speed_calibration_ids, key=_camera_sort_key)
    missing_rois = sorted(manifest_set - roi_ids, key=_camera_sort_key)
    missing_flow_lines = sorted(manifest_set - flow_line_ids, key=_camera_sort_key)

    fully_configured = sorted(
        manifest_set & coordinate_ids & threshold_ids & roi_ids & flow_line_ids,
        key=_camera_sort_key,
    )

    queue_entries: list[dict[str, Any]] = []
    for camera_id in sorted(manifest_set, key=_camera_sort_key):
        missing: list[str] = []
        if camera_id not in coordinate_ids:
            missing.append("coordinates")
        if camera_id not in threshold_ids:
            missing.append("thresholds")
        if camera_id not in roi_ids:
            missing.append("rois")
        if camera_id not in flow_line_ids:
            missing.append("flow_lines")
        if not missing:
            continue
        camera = manifest_by_id.get(camera_id, {})
        queue_entries.append(
            {
                "camera_id": camera_id,
                "name": camera.get("name"),
                "district": camera.get("district"),
                "sub_district": camera.get("sub_district"),
                "missing": missing,
                "missing_count": len(missing),
            }
        )

    queue_entries.sort(
        key=lambda entry: (
            entry["missing_count"],
            _camera_sort_key(str(entry["camera_id"])),
        )
    )
    queue_limit = max(1, int(args.queue_limit))
    calibration_coverage = summarize_calibration_coverage(
        manifest_camera_ids,
        Path(args.data_dir),
        Path(args.calibration_file),
        min_history=int(args.calibration_min_history),
        offpeak_start=int(args.calibration_offpeak_start),
        offpeak_end=int(args.calibration_offpeak_end),
    )

    return {
        "manifest_file": str(args.manifest_file),
        "data_dir": str(args.data_dir),
        "camera_count": len(manifest_camera_ids),
        "fully_configured_count": len(fully_configured),
        "fully_configured_camera_ids": fully_configured,
        "missing_counts": {
            "coordinates": len(missing_coordinates),
            "thresholds": len(missing_thresholds),
            "speed_calibration": len(missing_speed_calibrations),
            "rois": len(missing_rois),
            "flow_lines": len(missing_flow_lines),
        },
        "missing_camera_ids": {
            "coordinates": missing_coordinates,
            "thresholds": missing_thresholds,
            "speed_calibration": missing_speed_calibrations,
            "rois": missing_rois,
            "flow_lines": missing_flow_lines,
        },
        "next_calibration_queue": queue_entries[:queue_limit],
        "speed_calibration": calibration_coverage,
        "config_files": {
            "coordinates": str(args.coordinates_file),
            "thresholds": str(args.thresholds_file),
            "speed_calibration": str(args.calibration_file),
            "rois": str(args.rois_file),
            "flow_lines": str(args.flow_lines_file),
        },
    }


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

    audit_config = subparsers.add_parser(
        "audit-config",
        help="Report which manifest cameras still need coordinates, ROI, flow lines, or thresholds",
    )
    audit_config.add_argument("--manifest-file", default="data/manifest.json")
    audit_config.add_argument("--data-dir", default="data")
    audit_config.add_argument("--coordinates-file", default="config/camera_coordinates.json")
    audit_config.add_argument("--thresholds-file", default=settings.camera_density_thresholds_path)
    audit_config.add_argument("--calibration-file", default=settings.camera_speed_calibration_path)
    audit_config.add_argument("--calibration-min-history", type=int, default=5)
    audit_config.add_argument("--calibration-offpeak-start", type=int, default=2)
    audit_config.add_argument("--calibration-offpeak-end", type=int, default=5)
    audit_config.add_argument("--rois-file", default=settings.roi_config_path)
    audit_config.add_argument("--flow-lines-file", default=settings.flow_line_config_path)
    audit_config.add_argument("--report-file", default=None)
    audit_config.add_argument("--queue-limit", type=int, default=20)
    audit_config.add_argument("--pretty", action="store_true")

    calibrate_freeflow = subparsers.add_parser(
        "calibrate-freeflow",
        help="Backfill per-camera free-flow speed calibration from persisted analysis history",
    )
    calibrate_freeflow.add_argument("--data-dir", default="data")
    calibrate_freeflow.add_argument("--config", default=settings.camera_speed_calibration_path)
    calibrate_freeflow.add_argument("--min-history", type=int, default=5)
    calibrate_freeflow.add_argument("--offpeak-start", type=int, default=2)
    calibrate_freeflow.add_argument("--offpeak-end", type=int, default=5)
    calibrate_freeflow.add_argument("--dry-run", action="store_true")
    calibrate_freeflow.add_argument("--pretty", action="store_true")

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


def _dispatch_audit_config(args: argparse.Namespace) -> int:
    report = _build_config_audit(args)
    if args.report_file:
        _write_json(args.report_file, report, pretty=args.pretty)
    _print_json(report, pretty=args.pretty)
    return 0


def _dispatch_calibrate_freeflow(args: argparse.Namespace) -> int:
    result = calibrate(
        Path(args.data_dir),
        Path(args.config),
        min_history=args.min_history,
        dry_run=args.dry_run,
        offpeak_start=args.offpeak_start,
        offpeak_end=args.offpeak_end,
    )
    payload = {
        "data_dir": str(args.data_dir),
        "config": str(args.config),
        "dry_run": bool(args.dry_run),
        "camera_count": len(result),
        "cameras": result,
    }
    _print_json(payload, pretty=args.pretty)
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
    if args.command == "audit-config":
        return _dispatch_audit_config(args)
    if args.command == "calibrate-freeflow":
        return _dispatch_calibrate_freeflow(args)
    if args.command == "serve":
        return _dispatch_serve(args)

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
