"""Persistent, serialized DeepStream appsrc inference worker."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any

VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "bicycle", "van", "taxi", "suv"}
FRAME_DURATION_NS = 200_000_000
WARMUP_WIDTH = 352
WARMUP_HEIGHT = 288


class DeepStreamEngine:
    def __init__(self, config_path: str, inference_timeout_seconds: float) -> None:
        if inference_timeout_seconds <= 0:
            raise ValueError("inference timeout must be positive")
        self.config_path = Path(config_path)
        self.inference_timeout_seconds = inference_timeout_seconds
        if not self.config_path.is_file():
            raise FileNotFoundError(f"TrafficCamNet config does not exist: {self.config_path}")

        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import GLib, Gst
        import pyds

        self._GLib = GLib
        self._Gst = Gst
        self._pyds = pyds
        self._Gst.init(None)

        self._request_lock = threading.Lock()
        self._condition = threading.Condition()
        self._pipeline = None
        self._appsrc = None
        self._loop = None
        self._loop_thread: threading.Thread | None = None
        self._width: int | None = None
        self._height: int | None = None
        self._next_pts = 0
        self._pending_indices: dict[int, int] = {}
        self._completed: dict[int, list[dict[str, Any]]] = {}
        self._failure: str | None = None
        self._ready = False

    @property
    def is_ready(self) -> bool:
        with self._condition:
            return self._ready and self._failure is None

    def start(self) -> None:
        with self._request_lock:
            self._ensure_pipeline(WARMUP_WIDTH, WARMUP_HEIGHT)
            warmup_frame = bytes(WARMUP_WIDTH * WARMUP_HEIGHT * 3)
            result = self._submit([warmup_frame], WARMUP_WIDTH, WARMUP_HEIGHT)
            if len(result) != 1:
                raise RuntimeError("TrafficCamNet warmup returned an invalid frame count")
            with self._condition:
                self._ready = True

    def infer(
        self,
        frames: list[bytes],
        width: int,
        height: int,
    ) -> list[list[dict[str, Any]]]:
        if not frames:
            raise ValueError("DeepStream inference requires at least one frame")
        expected_size = width * height * 3
        if any(len(frame) != expected_size for frame in frames):
            raise ValueError("decoded RGB frame size did not match its dimensions")
        with self._request_lock:
            with self._condition:
                if not self._ready or self._failure:
                    raise RuntimeError(self._failure or "TrafficCamNet engine is not ready")
            self._ensure_pipeline(width, height)
            results = self._submit(frames, width, height)
            with self._condition:
                self._ready = True
            return results

    def close(self) -> None:
        with self._request_lock:
            self._stop_pipeline()

    def _ensure_pipeline(self, width: int, height: int) -> None:
        if (
            self._pipeline is not None
            and self._width == width
            and self._height == height
            and self._failure is None
        ):
            return
        with self._condition:
            self._ready = False
        self._stop_pipeline()
        self._failure = None
        description = (
            f"appsrc name=source is-live=true format=time block=true do-timestamp=false "
            f"caps=video/x-raw,format=RGB,width={width},height={height},framerate=5/1 ! "
            "queue max-size-buffers=8 max-size-bytes=0 max-size-time=0 ! "
            "videoconvert ! nvvideoconvert ! "
            "video/x-raw(memory:NVMM),format=NV12 ! "
            "mux.sink_0 "
            f"nvstreammux name=mux batch-size=1 width={width} height={height} "
            "live-source=1 batched-push-timeout=40000 ! "
            f'nvinfer name=infer config-file-path="{self.config_path}" batch-size=1 ! '
            "fakesink sync=false async=false"
        )
        pipeline = self._Gst.parse_launch(description)
        source = pipeline.get_by_name("source")
        infer = pipeline.get_by_name("infer")
        if source is None or infer is None:
            raise RuntimeError("DeepStream pipeline is missing appsrc or nvinfer")
        infer_pad = infer.get_static_pad("src")
        if infer_pad is None:
            raise RuntimeError("DeepStream pipeline has no nvinfer source pad")
        infer_pad.add_probe(self._Gst.PadProbeType.BUFFER, self._on_infer_output, None)

        loop = self._GLib.MainLoop()
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        thread = threading.Thread(target=loop.run, name="trafficcamnet-gstreamer", daemon=True)
        thread.start()
        state_change = pipeline.set_state(self._Gst.State.PLAYING)
        if state_change == self._Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(self._Gst.State.NULL)
            loop.quit()
            thread.join(timeout=2)
            raise RuntimeError("DeepStream failed to start the TrafficCamNet pipeline")

        self._pipeline = pipeline
        self._appsrc = source
        self._loop = loop
        self._loop_thread = thread
        self._width = width
        self._height = height
        self._appsrc.set_property("max-bytes", width * height * 3 * 4)

    def _submit(
        self,
        frames: list[bytes],
        width: int,
        height: int,
    ) -> list[list[dict[str, Any]]]:
        if self._appsrc is None:
            raise RuntimeError("DeepStream appsrc is unavailable")
        timestamps = []
        with self._condition:
            if self._failure:
                raise RuntimeError(self._failure)
            for index in range(len(frames)):
                pts = self._next_pts
                self._next_pts += FRAME_DURATION_NS
                self._pending_indices[pts] = index
                timestamps.append(pts)

        for pts, frame in zip(timestamps, frames):
            buffer = self._Gst.Buffer.new_allocate(None, len(frame), None)
            buffer.fill(0, frame)
            buffer.pts = pts
            buffer.dts = pts
            buffer.duration = FRAME_DURATION_NS
            flow = self._appsrc.emit("push-buffer", buffer)
            if flow != self._Gst.FlowReturn.OK:
                self._discard_pending(timestamps)
                self._mark_failed(f"DeepStream appsrc rejected a frame: {flow}")
                raise RuntimeError(f"DeepStream appsrc rejected a frame: {flow}")

        deadline = time.monotonic() + self.inference_timeout_seconds
        with self._condition:
            while any(pts not in self._completed for pts in timestamps):
                if self._failure:
                    self._discard_pending_locked(timestamps)
                    raise RuntimeError(self._failure)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._discard_pending_locked(timestamps)
                    self._ready = False
                    self._failure = "timed out waiting for all frame metadata"
                    raise TimeoutError(self._failure)
                self._condition.wait(remaining)
            results = [self._completed.pop(pts) for pts in timestamps]
            return results

    def _on_infer_output(self, _pad: Any, info: Any, _data: Any):
        buffer = info.get_buffer()
        if buffer is None:
            return self._Gst.PadProbeReturn.OK
        try:
            batch_meta = self._pyds.gst_buffer_get_nvds_batch_meta(hash(buffer))
            if batch_meta is None:
                raise RuntimeError("DeepStream output buffer has no batch metadata")
            for frame_data in self._iter_linked_list(batch_meta.frame_meta_list):
                frame_meta = self._pyds.NvDsFrameMeta.cast(frame_data)
                pts = int(frame_meta.buf_pts)
                detections = []
                for object_data in self._iter_linked_list(frame_meta.obj_meta_list):
                    obj = self._pyds.NvDsObjectMeta.cast(object_data)
                    label = str(obj.obj_label).strip().lower()
                    if label not in VEHICLE_LABELS:
                        continue
                    confidence = float(obj.confidence)
                    rect = obj.rect_params
                    left = max(0.0, min(float(self._width), float(rect.left)))
                    top = max(0.0, min(float(self._height), float(rect.top)))
                    right = max(0.0, min(float(self._width), float(rect.left + rect.width)))
                    bottom = max(0.0, min(float(self._height), float(rect.top + rect.height)))
                    if (
                        not math.isfinite(confidence)
                        or not 0 <= confidence <= 1
                        or right <= left
                        or bottom <= top
                    ):
                        raise RuntimeError("DeepStream returned an invalid vehicle detection")
                    detections.append(
                        {
                            "label": label,
                            "confidence": confidence,
                            "box": {
                                "xmin": left,
                                "ymin": top,
                                "xmax": right,
                                "ymax": bottom,
                            },
                        }
                    )

                with self._condition:
                    frame_index = self._pending_indices.pop(pts, None)
                    if frame_index is None:
                        raise RuntimeError(f"DeepStream returned unexpected frame PTS {pts}")
                    self._completed[pts] = detections
                    self._condition.notify_all()
        except Exception as exc:
            self._mark_failed(f"DeepStream metadata processing failed: {exc}")
        return self._Gst.PadProbeReturn.OK

    def _on_bus_message(self, _bus: Any, message: Any):
        if message.type == self._Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self._mark_failed(f"{error}: {debug}")
        elif message.type == self._Gst.MessageType.EOS:
            self._mark_failed("unexpected end-of-stream from persistent appsrc pipeline")
        return True

    @staticmethod
    def _iter_linked_list(node: Any):
        while node is not None:
            try:
                yield node.data
                node = node.next
            except StopIteration:
                return

    def _mark_failed(self, message: str) -> None:
        with self._condition:
            self._failure = message
            self._ready = False
            self._condition.notify_all()

    def _discard_pending(self, timestamps: list[int]) -> None:
        with self._condition:
            self._discard_pending_locked(timestamps)

    def _discard_pending_locked(self, timestamps: list[int]) -> None:
        for pts in timestamps:
            self._pending_indices.pop(pts, None)
            self._completed.pop(pts, None)

    def _stop_pipeline(self) -> None:
        pipeline = self._pipeline
        loop = self._loop
        thread = self._loop_thread
        self._pipeline = None
        self._appsrc = None
        self._loop = None
        self._loop_thread = None
        self._width = None
        self._height = None
        if pipeline is not None:
            pipeline.set_state(self._Gst.State.NULL)
        if loop is not None:
            loop.quit()
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
            if thread.is_alive():
                raise RuntimeError("DeepStream GLib main loop did not stop")
