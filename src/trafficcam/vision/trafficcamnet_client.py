"""HTTP client for the Docker-backed TrafficCamNet burst inference service."""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trafficcam.config import settings

from .density_scorer import DensityScorer


class TrafficCamNetClientError(RuntimeError):
    """Raised when the TrafficCamNet service fails or violates its contract."""


class TrafficCamNetClient:
    supports_burst = True
    backend = "trafficcamnet"
    model_name = "resnet18_trafficcamnet_pruned.onnx"

    def __init__(
        self,
        service_url: str | None = None,
        timeout_seconds: float | None = None,
        max_burst_frames: int | None = None,
        max_burst_bytes: int | None = None,
    ) -> None:
        self.service_url = (service_url or settings.vision_trafficcamnet_url).rstrip("/")
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.vision_trafficcamnet_timeout_seconds
        )
        self.max_burst_frames = (
            max_burst_frames
            if max_burst_frames is not None
            else settings.vision_trafficcamnet_max_burst_frames
        )
        self.max_burst_bytes = (
            max_burst_bytes
            if max_burst_bytes is not None
            else settings.vision_trafficcamnet_max_burst_bytes
        )
        if self.timeout_seconds <= 0:
            raise ValueError("TrafficCamNet timeout must be positive")
        if self.max_burst_frames <= 0 or self.max_burst_bytes <= 0:
            raise ValueError("TrafficCamNet burst limits must be positive")

    def analyze(self, image_path: str, camera_id: str | None = None) -> dict[str, Any]:
        """Analyze one frame using the burst endpoint."""
        return self.analyze_burst([image_path], camera_id=camera_id)[0]

    def analyze_burst(
        self,
        frame_paths: list[str],
        camera_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Submit one ordered frame burst and validate the ordered response."""
        if not frame_paths:
            raise ValueError("TrafficCamNet burst must contain at least one frame")
        if len(frame_paths) > self.max_burst_frames:
            raise ValueError(
                f"TrafficCamNet burst has {len(frame_paths)} frames; "
                f"limit is {self.max_burst_frames}"
            )
        if not camera_id:
            raise ValueError("TrafficCamNet burst requires a camera_id")

        frames: list[dict[str, Any]] = []
        total_bytes = 0
        for index, frame_path in enumerate(frame_paths):
            image_bytes = Path(frame_path).read_bytes()
            if not image_bytes.startswith(b"\xff\xd8"):
                raise ValueError(f"TrafficCamNet input is not a JPEG image: {frame_path}")
            total_bytes += len(image_bytes)
            if total_bytes > self.max_burst_bytes:
                raise ValueError(
                    f"TrafficCamNet burst exceeds {self.max_burst_bytes} input bytes"
                )
            frames.append(
                {
                    "frame_index": index,
                    "jpeg_base64": base64.b64encode(image_bytes).decode("ascii"),
                }
            )

        request_body = json.dumps(
            {
                "schema_version": 1,
                "camera_id": camera_id,
                "frames": frames,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(request_body) > self.max_burst_bytes * 2:
            raise ValueError("Encoded TrafficCamNet burst request exceeds its size limit")
        request = Request(
            f"{self.service_url}/v1/infer-burst",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read(self.max_burst_bytes * 2 + 1)
        except HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise TrafficCamNetClientError(
                f"TrafficCamNet service returned HTTP {exc.code}: {detail}"
            ) from exc
        except TimeoutError as exc:
            raise TrafficCamNetClientError(
                "TrafficCamNet service request timed out"
            ) from exc
        except URLError as exc:
            raise TrafficCamNetClientError(
                f"TrafficCamNet service request failed: {exc.reason}"
            ) from exc

        if len(response_body) > self.max_burst_bytes * 2:
            raise TrafficCamNetClientError("TrafficCamNet response exceeded its size limit")
        try:
            payload = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TrafficCamNetClientError("TrafficCamNet returned invalid JSON") from exc
        return self._normalize_response(payload, frame_paths, camera_id)

    def _normalize_response(
        self,
        payload: Any,
        frame_paths: list[str],
        camera_id: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise TrafficCamNetClientError("TrafficCamNet response has an unsupported schema")
        if payload.get("backend") != self.backend:
            raise TrafficCamNetClientError("TrafficCamNet response backend did not match")
        if payload.get("camera_id") != camera_id:
            raise TrafficCamNetClientError("TrafficCamNet response camera_id did not match")
        model_name = payload.get("model")
        frames = payload.get("frames")
        if not isinstance(model_name, str) or not model_name:
            raise TrafficCamNetClientError("TrafficCamNet response is missing model identity")
        if not isinstance(frames, list) or len(frames) != len(frame_paths):
            raise TrafficCamNetClientError(
                "TrafficCamNet response frame count did not match the request"
            )

        results = []
        for expected_index, (frame_path, frame) in enumerate(zip(frame_paths, frames)):
            if not isinstance(frame, dict) or frame.get("frame_index") != expected_index:
                raise TrafficCamNetClientError(
                    f"TrafficCamNet response frame order mismatch at index {expected_index}"
                )
            detections = frame.get("detections")
            if not isinstance(detections, list):
                raise TrafficCamNetClientError(
                    f"TrafficCamNet detections were invalid at frame {expected_index}"
                )
            normalized_detections = [
                self._normalize_detection(detection, expected_index)
                for detection in detections
            ]
            confidence = (
                sum(detection["confidence"] for detection in normalized_detections)
                / len(normalized_detections)
                if normalized_detections
                else 0.0
            )
            results.append(
                {
                    "image_path": frame_path,
                    "label": DensityScorer(camera_id=camera_id).from_count(
                        len(normalized_detections)
                    ),
                    "confidence": round(confidence, 4),
                    "detections": normalized_detections,
                    "vehicle_count": len(normalized_detections),
                    "backend": self.backend,
                    "model_name": model_name,
                }
            )
        return results

    @staticmethod
    def _normalize_detection(detection: Any, frame_index: int) -> dict[str, Any]:
        if not isinstance(detection, dict):
            raise TrafficCamNetClientError(
                f"TrafficCamNet returned an invalid detection at frame {frame_index}"
            )
        label = detection.get("label")
        confidence = detection.get("confidence")
        box = detection.get("box")
        if not isinstance(label, str) or not label:
            raise TrafficCamNetClientError(
                f"TrafficCamNet returned an invalid label at frame {frame_index}"
            )
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise TrafficCamNetClientError(
                f"TrafficCamNet returned invalid confidence at frame {frame_index}"
            )
        if not isinstance(box, dict):
            raise TrafficCamNetClientError(
                f"TrafficCamNet returned an invalid box at frame {frame_index}"
            )
        coordinates = {}
        for coordinate in ("xmin", "ymin", "xmax", "ymax"):
            value = box.get(coordinate)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise TrafficCamNetClientError(
                    f"TrafficCamNet returned invalid box coordinates at frame {frame_index}"
                )
            coordinates[coordinate] = float(value)
        if coordinates["xmax"] <= coordinates["xmin"] or coordinates["ymax"] <= coordinates["ymin"]:
            raise TrafficCamNetClientError(
                f"TrafficCamNet returned an empty box at frame {frame_index}"
            )
        return {
            "label": label.strip().lower(),
            "confidence": float(confidence),
            "box": coordinates,
        }
