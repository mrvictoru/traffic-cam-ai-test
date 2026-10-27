"""Versioned internal HTTP API for ordered TrafficCamNet frame bursts."""

from __future__ import annotations

import base64
import binascii
import math
import os
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, Callable, Literal, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

MAX_FRAMES = int(os.getenv("TRAFFICCAMNET_MAX_FRAMES", "30"))
MAX_BURST_BYTES = int(os.getenv("TRAFFICCAMNET_MAX_BURST_BYTES", str(16 * 1024 * 1024)))
MAX_FRAME_BYTES = int(os.getenv("TRAFFICCAMNET_MAX_FRAME_BYTES", str(2 * 1024 * 1024)))
MAX_REQUEST_BYTES = MAX_BURST_BYTES * 4 // 3 + 128 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_DECODED_BURST_BYTES = 64 * 1024 * 1024
MODEL_NAME = "resnet18_trafficcamnet_pruned.onnx"
VEHICLE_LABELS = {"car", "truck", "bus", "motorcycle", "bicycle", "van", "taxi", "suv"}


class Engine(Protocol):
    @property
    def is_ready(self) -> bool: ...

    def start(self) -> None: ...

    def infer(self, frames: list[bytes], width: int, height: int) -> list[list[dict[str, Any]]]: ...

    def close(self) -> None: ...


class BurstFrame(BaseModel):
    frame_index: int = Field(ge=0)
    jpeg_base64: str = Field(min_length=4, max_length=(MAX_FRAME_BYTES * 4 // 3) + 8)


class InferBurstRequest(BaseModel):
    schema_version: Literal[1]
    camera_id: str = Field(min_length=1, max_length=64)
    frames: list[BurstFrame] = Field(min_length=1, max_length=MAX_FRAMES)


def _create_engine() -> Engine:
    from .deepstream_engine import DeepStreamEngine

    return DeepStreamEngine(
        config_path=os.getenv(
            "TRAFFICCAMNET_CONFIG_PATH",
            "/test/config_infer_primary.txt",
        ),
        inference_timeout_seconds=float(
            os.getenv("TRAFFICCAMNET_INFERENCE_TIMEOUT_SECONDS", "15")
        ),
    )


def _decode_burst(
    request: InferBurstRequest,
) -> tuple[int, int, list[bytes]]:
    total_encoded_bytes = 0
    total_decoded_bytes = 0
    decoded_frames: list[bytes] = []
    expected_dimensions: tuple[int, int] | None = None

    for expected_index, frame in enumerate(request.frames):
        if frame.frame_index != expected_index:
            raise HTTPException(
                status_code=422,
                detail=f"frame_index values must be ordered from zero; got {frame.frame_index} at {expected_index}",
            )
        try:
            jpeg_bytes = base64.b64decode(frame.jpeg_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"frame {expected_index} contains invalid base64",
            ) from exc
        if not jpeg_bytes or len(jpeg_bytes) > MAX_FRAME_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"frame {expected_index} exceeds the JPEG size limit",
            )
        total_encoded_bytes += len(jpeg_bytes)
        if total_encoded_bytes > MAX_BURST_BYTES:
            raise HTTPException(status_code=413, detail="burst exceeds the JPEG size limit")

        try:
            with Image.open(BytesIO(jpeg_bytes)) as image:
                if image.format != "JPEG":
                    raise HTTPException(
                        status_code=422,
                        detail=f"frame {expected_index} is not a JPEG image",
                    )
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=f"frame {expected_index} has unsupported dimensions",
                    )
                if expected_dimensions is None:
                    expected_dimensions = (width, height)
                elif expected_dimensions != (width, height):
                    raise HTTPException(
                        status_code=422,
                        detail="all frames in a burst must have identical dimensions",
                    )
                image.load()
                rgb_bytes = image.convert("RGB").tobytes()
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=f"frame {expected_index} is not a decodable JPEG",
            ) from exc

        total_decoded_bytes += len(rgb_bytes)
        if total_decoded_bytes > MAX_DECODED_BURST_BYTES:
            raise HTTPException(status_code=413, detail="decoded burst exceeds its size limit")
        decoded_frames.append(rgb_bytes)

    if expected_dimensions is None:
        raise HTTPException(status_code=422, detail="burst contains no decodable frames")
    return expected_dimensions[0], expected_dimensions[1], decoded_frames


def create_app(engine_factory: Callable[[], Engine] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = (engine_factory or _create_engine)()
        app.state.engine = engine
        try:
            engine.start()
            yield
        finally:
            engine.close()

    app = FastAPI(title="TrafficCamNet inference", version="1", lifespan=lifespan)

    @app.middleware("http")
    async def enforce_request_size(request: Request, call_next):
        if request.url.path == "/v1/infer-burst":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    request_size = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "invalid Content-Length"},
                    )
                if request_size > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "burst request exceeds its size limit"},
                    )
        return await call_next(request)

    @app.get("/healthz")
    def healthz(request: Request):
        engine: Engine | None = getattr(request.app.state, "engine", None)
        if engine is None or not engine.is_ready:
            raise HTTPException(status_code=503, detail="TrafficCamNet model is not ready")
        return {
            "status": "ready",
            "schema_version": 1,
            "backend": "trafficcamnet",
            "model": MODEL_NAME,
        }

    @app.post("/v1/infer-burst")
    def infer_burst(payload: InferBurstRequest, request: Request):
        engine: Engine | None = getattr(request.app.state, "engine", None)
        if engine is None or not engine.is_ready:
            raise HTTPException(status_code=503, detail="TrafficCamNet model is not ready")
        width, height, decoded_frames = _decode_burst(payload)
        try:
            detections_by_frame = engine.infer(decoded_frames, width, height)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=f"TrafficCamNet inference timed out: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"TrafficCamNet inference failed: {exc}") from exc

        if len(detections_by_frame) != len(payload.frames):
            raise HTTPException(
                status_code=503,
                detail="TrafficCamNet returned a different number of frames than requested",
            )
        response_frames = []
        for frame_index, detections in enumerate(detections_by_frame):
            if not isinstance(detections, list):
                raise HTTPException(
                    status_code=503,
                    detail=f"TrafficCamNet returned invalid detections for frame {frame_index}",
                )
            vehicle_detections = []
            for detection in detections:
                if not isinstance(detection, dict):
                    raise HTTPException(
                        status_code=503,
                        detail=f"TrafficCamNet returned an invalid detection for frame {frame_index}",
                    )
                label = detection.get("label")
                if not isinstance(label, str):
                    raise HTTPException(
                        status_code=503,
                        detail=f"TrafficCamNet returned an invalid label for frame {frame_index}",
                    )
                label = label.strip().lower()
                if label not in VEHICLE_LABELS:
                    continue
                confidence = detection.get("confidence")
                box = detection.get("box")
                if (
                    isinstance(confidence, bool)
                    or not isinstance(confidence, (int, float))
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                    or not isinstance(box, dict)
                ):
                    raise HTTPException(
                        status_code=503,
                        detail=f"TrafficCamNet returned invalid detection data for frame {frame_index}",
                    )
                coordinates = {}
                for key in ("xmin", "ymin", "xmax", "ymax"):
                    value = box.get(key)
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                    ):
                        raise HTTPException(
                            status_code=503,
                            detail=f"TrafficCamNet returned invalid box coordinates for frame {frame_index}",
                        )
                    coordinates[key] = float(value)
                if (
                    coordinates["xmin"] < 0
                    or coordinates["ymin"] < 0
                    or coordinates["xmax"] > width
                    or coordinates["ymax"] > height
                    or coordinates["xmax"] <= coordinates["xmin"]
                    or coordinates["ymax"] <= coordinates["ymin"]
                ):
                    raise HTTPException(
                        status_code=503,
                        detail=f"TrafficCamNet returned an out-of-bounds box for frame {frame_index}",
                    )
                vehicle_detections.append(
                    {
                        "label": label,
                        "confidence": float(confidence),
                        "box": coordinates,
                    }
                )
            response_frames.append(
                {
                    "frame_index": frame_index,
                    "detections": vehicle_detections,
                }
            )
        return {
            "schema_version": 1,
            "backend": "trafficcamnet",
            "model": MODEL_NAME,
            "camera_id": payload.camera_id,
            "frames": response_frames,
        }

    return app


app = create_app()
