from __future__ import annotations

import base64
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from tools.trafficcamnet_service.app import create_app


class FakeEngine:
    def __init__(self, *, fail: bool = False):
        self._ready = False
        self.fail = fail
        self.calls = []

    @property
    def is_ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        self._ready = True

    def infer(self, frames: list[bytes], width: int, height: int):
        self.calls.append((frames, width, height))
        if self.fail:
            raise RuntimeError("test inference failure")
        return [
            [
                {
                    "label": "car",
                    "confidence": 0.8,
                    "box": {"xmin": 1.0, "ymin": 2.0, "xmax": 20.0, "ymax": 20.0},
                },
                {
                    "label": "person",
                    "confidence": 0.9,
                    "box": {"xmin": 4.0, "ymin": 5.0, "xmax": 10.0, "ymax": 15.0},
                },
            ]
            for _ in frames
        ]

    def close(self) -> None:
        self._ready = False


def _jpeg(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format="JPEG")
    return output.getvalue()


def _request_payload(frames: list[bytes]) -> dict:
    return {
        "schema_version": 1,
        "camera_id": "camera-17",
        "frames": [
            {
                "frame_index": index,
                "jpeg_base64": base64.b64encode(frame).decode("ascii"),
            }
            for index, frame in enumerate(frames)
        ],
    }


def test_health_is_ready_only_after_engine_start() -> None:
    engine = FakeEngine()
    with TestClient(create_app(engine_factory=lambda: engine)) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "schema_version": 1,
            "backend": "trafficcamnet",
            "model": "resnet18_trafficcamnet_pruned.onnx",
        }


def test_burst_endpoint_preserves_order_and_filters_non_vehicle_classes() -> None:
    engine = FakeEngine()
    frames = [_jpeg((20, 30, 40)), _jpeg((50, 60, 70))]
    with TestClient(create_app(engine_factory=lambda: engine)) as client:
        response = client.post("/v1/infer-burst", json=_request_payload(frames))

    assert response.status_code == 200
    payload = response.json()
    assert payload["camera_id"] == "camera-17"
    assert [frame["frame_index"] for frame in payload["frames"]] == [0, 1]
    assert all(
        [detection["label"] for detection in frame["detections"]] == ["car"]
        for frame in payload["frames"]
    )
    assert engine.calls[0][1:] == (32, 24)
    assert len(engine.calls[0][0]) == 2


def test_burst_endpoint_rejects_unordered_frames() -> None:
    payload = _request_payload([_jpeg((20, 30, 40)), _jpeg((50, 60, 70))])
    payload["frames"][1]["frame_index"] = 3
    with TestClient(create_app(engine_factory=FakeEngine)) as client:
        response = client.post("/v1/infer-burst", json=payload)
    assert response.status_code == 422


def test_burst_endpoint_rejects_mixed_dimensions() -> None:
    first = BytesIO()
    Image.new("RGB", (32, 24)).save(first, format="JPEG")
    second = BytesIO()
    Image.new("RGB", (40, 24)).save(second, format="JPEG")
    with TestClient(create_app(engine_factory=FakeEngine)) as client:
        response = client.post(
            "/v1/infer-burst",
            json=_request_payload([first.getvalue(), second.getvalue()]),
        )
    assert response.status_code == 422


def test_inference_failure_is_an_explicit_service_error() -> None:
    with TestClient(create_app(engine_factory=lambda: FakeEngine(fail=True))) as client:
        response = client.post("/v1/infer-burst", json=_request_payload([_jpeg((1, 2, 3))]))
    assert response.status_code == 503
    assert "test inference failure" in response.json()["detail"]
