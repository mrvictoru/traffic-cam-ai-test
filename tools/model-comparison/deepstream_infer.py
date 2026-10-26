"""Run TrafficCamNet and export per-frame detections and timing metrics."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst
import pyds

Gst.init(None)

VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "bicycle", "van", "taxi", "suv"}


def summarize(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median_ms": None, "p95_ms": None}
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return {"median_ms": round(statistics.median(ordered), 3), "p95_ms": round(ordered[index], 3)}


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


def _iter_linked_list(node: Any):
    while node is not None:
        try:
            data = node.data
        except StopIteration:
            break
        yield data
        try:
            node = node.next
        except StopIteration:
            break


def run_clip(
    clip: Path,
    model_config: Path,
    out_dir: Path,
    duration_seconds: int,
    fps: int,
) -> dict[str, Any]:
    round_name = clip.parent.name
    camera_id = clip.name.split("-")[1]
    sink_start_ns: dict[int, int] = {}
    frames: dict[int, dict[str, Any]] = {}
    stage_ms: list[float] = []
    first_output_ns: int | None = None
    started_ns = time.perf_counter_ns()
    play_started_ns: int | None = None
    pipeline: Gst.Pipeline | None = None
    loop = GLib.MainLoop()
    errors: list[str] = []
    sampler = GpuMemorySampler()

    def frame_meta_list(buffer: Gst.Buffer):
        batch = pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
        if batch is None:
            return []
        return list(_iter_linked_list(batch.frame_meta_list))

    def on_infer_sink(_pad: Gst.Pad, info: Gst.PadProbeInfo, _data: Any):
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        now_ns = time.perf_counter_ns()
        for data in frame_meta_list(buffer):
            meta = pyds.NvDsFrameMeta.cast(data)
            sink_start_ns[int(meta.frame_num)] = now_ns
        return Gst.PadProbeReturn.OK

    def on_infer_src(_pad: Gst.Pad, info: Gst.PadProbeInfo, _data: Any):
        nonlocal first_output_ns
        buffer = info.get_buffer()
        if buffer is None:
            return Gst.PadProbeReturn.OK
        now_ns = time.perf_counter_ns()
        for data in frame_meta_list(buffer):
            frame_meta = pyds.NvDsFrameMeta.cast(data)
            frame_index = int(frame_meta.frame_num)
            if first_output_ns is None:
                first_output_ns = now_ns
            elapsed = now_ns - sink_start_ns.pop(frame_index, now_ns)
            latency_ms = elapsed / 1_000_000
            stage_ms.append(latency_ms)
            detections = []
            for object_data in _iter_linked_list(frame_meta.obj_meta_list):
                obj = pyds.NvDsObjectMeta.cast(object_data)
                label = str(obj.obj_label).strip().lower()
                rect = obj.rect_params
                detections.append(
                    {
                        "label": label,
                        "class_id": int(obj.class_id),
                        "confidence": float(obj.confidence),
                        "is_vehicle": label in VEHICLE_LABELS,
                        "box": {
                            "xmin": float(rect.left),
                            "ymin": float(rect.top),
                            "xmax": float(rect.left + rect.width),
                            "ymax": float(rect.top + rect.height),
                        },
                    }
                )
            frames[frame_index] = {
                "frame_index": frame_index,
                "detections": detections,
                "vehicle_detections": [det for det in detections if det["is_vehicle"]],
                "vehicle_count": sum(det["is_vehicle"] for det in detections),
                "nvinfer_stage_elapsed_ms": round(latency_ms, 3),
            }
        return Gst.PadProbeReturn.OK

    def on_bus_message(_bus: Gst.Bus, message: Gst.Message):
        if message.type == Gst.MessageType.EOS:
            loop.quit()
        elif message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            errors.append(f"{error}: {debug}")
            loop.quit()
        return True

    pipeline_description = (
        f'filesrc location="{clip}" ! qtdemux ! h264parse ! nvv4l2decoder ! '
        f'identity eos-after={duration_seconds * fps + 1} ! queue ! mux.sink_0 '
        f'nvstreammux name=mux batch-size=1 width=352 height=288 live-source=0 '
        f'batched-push-timeout=40000 ! '
        f'nvinfer name=infer config-file-path="{model_config}" batch-size=1 ! '
        f'fakesink sync=false'
    )
    pipeline = Gst.parse_launch(pipeline_description)
    infer = pipeline.get_by_name("infer")
    if infer is None:
        raise RuntimeError("GStreamer pipeline has no nvinfer element")
    for pad_name, callback in (("sink", on_infer_sink), ("src", on_infer_src)):
        pad = infer.get_static_pad(pad_name)
        if pad is None:
            raise RuntimeError(f"could not get nvinfer {pad_name} pad")
        pad.add_probe(Gst.PadProbeType.BUFFER, callback, None)
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", on_bus_message)
    sampler.start()
    try:
        play_started_ns = time.perf_counter_ns()
        state = pipeline.set_state(Gst.State.PLAYING)
        if state == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("GStreamer failed to start the TrafficCamNet pipeline")
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        sampler.stop()
    elapsed_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000
    if errors:
        raise RuntimeError("; ".join(errors))
    ordered_frames = [frames[index] for index in sorted(frames)]
    if not ordered_frames:
        raise RuntimeError(f"TrafficCamNet produced no frame metadata for {clip}")
    expected_frames = duration_seconds * fps
    if len(ordered_frames) != expected_frames:
        raise RuntimeError(
            f"TrafficCamNet processed {len(ordered_frames)} frames from {clip}; "
            f"expected {expected_frames} at {fps} FPS for {duration_seconds} seconds"
        )
    frame_dir = Path("frames") / round_name / f"cam-{camera_id}"
    for position, frame in enumerate(ordered_frames, start=1):
        frame["frame_path"] = str(frame_dir / f"frame_{position:06d}.jpg")
    result = {
        "schema_version": 1,
        "backend": "trafficcamnet",
        "model": "resnet18_trafficcamnet_pruned.onnx",
        "precision": "INT8",
        "camera_id": camera_id,
        "round": round_name,
        "source_clip": str(clip),
        "requested_duration_seconds": duration_seconds,
        "frame_count": len(ordered_frames),
        "first_detection_after_play_ms": round(
            ((first_output_ns or play_started_ns or started_ns) - (play_started_ns or started_ns))
            / 1_000_000,
            3,
        ),
        "nvinfer_stage": summarize(stage_ms),
        "processing_wall_seconds_including_decode": round(elapsed_seconds, 3),
        "effective_frames_per_second": round(len(ordered_frames) / elapsed_seconds, 3),
        "gpu_device_memory_sampled_peak_mib_including_other_processes": max(
            sampler.samples_mib, default=None
        ),
        "gpu_memory_sample_count": len(sampler.samples_mib),
        "frames": ordered_frames,
    }
    result_path = (
        out_dir
        / "detections"
        / "trafficcamnet"
        / round_name
        / f"cam-{camera_id}-{duration_seconds}s.json"
    )
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(
        f"TrafficCamNet {round_name} camera {camera_id}: {len(ordered_frames)} frames, "
        f"{elapsed_seconds:.1f}s wall, first detection "
        f"{result['first_detection_after_play_ms']}ms, nvinfer median "
        f"{result['nvinfer_stage']['median_ms']}ms/frame"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--model-config", type=Path, default=Path("/test/config_infer_primary.txt"))
    parser.add_argument("--duration-seconds", type=int, choices=(30, 120), default=120)
    parser.add_argument("--fps", type=int, default=5)
    parser.add_argument("--camera-id")
    parser.add_argument("--round")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if args.fps != 5:
        parser.error("DeepStream frame_num sampling currently expects the captured 5-FPS clips")
    clips = sorted(run_dir.glob("round-*/cam-*-120s.mp4"))
    if args.camera_id:
        clips = [clip for clip in clips if clip.name.startswith(f"cam-{args.camera_id}-")]
    if args.round:
        clips = [clip for clip in clips if clip.parent.name == args.round]
    if not clips:
        parser.error(f"no captured 120-second clips found in {run_dir}")
    config = args.model_config
    for clip in clips:
        run_clip(clip, config, run_dir, args.duration_seconds, args.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
