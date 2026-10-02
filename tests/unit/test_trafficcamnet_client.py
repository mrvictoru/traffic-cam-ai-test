from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.error import URLError

import pytest

from trafficcam.vision.trafficcamnet_client import (
    TrafficCamNetClient,
    TrafficCamNetClientError,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self._body


def _frame_response(frame_index: int, label: str = "car") -> dict:
    return {
        "frame_index": frame_index,
        "detections": [
            {
                "label": label,
                "confidence": 0.75,
                "box": {"xmin": 1, "ymin": 2, "xmax": 20, "ymax": 30},
            }
        ],
    }


def _write_jpegs(tmp_path: Path, count: int = 2) -> list[str]:
    paths = []
    for index in range(count):
        path = tmp_path / f"frame-{index}.jpg"
        path.write_bytes(b"\xff\xd8" + bytes([index]) + b"\xff\xd9")
        paths.append(str(path))
    return paths


def test_analyze_burst_sends_one_ordered_request_and_normalizes_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _write_jpegs(tmp_path)
    payload = {
        "schema_version": 1,
        "backend": "trafficcamnet",
        "model": "resnet18_trafficcamnet_pruned.onnx",
        "camera_id": "camera-7",
        "frames": [_frame_response(0), _frame_response(1, "bus")],
    }
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(payload)

    monkeypatch.setattr(
        "trafficcam.vision.trafficcamnet_client.urlopen",
        fake_urlopen,
    )
    client = TrafficCamNetClient(
        service_url="http://vision:8080/",
        timeout_seconds=4,
    )

    results = client.analyze_burst(paths, camera_id="camera-7")

    assert len(requests) == 1
    request, timeout = requests[0]
    sent = json.loads(request.data)
    assert request.full_url == "http://vision:8080/v1/infer-burst"
    assert timeout == 4
    assert sent["camera_id"] == "camera-7"
    assert [frame["frame_index"] for frame in sent["frames"]] == [0, 1]
    assert [
        base64.b64decode(frame["jpeg_base64"])
        for frame in sent["frames"]
    ] == [Path(path).read_bytes() for path in paths]
    assert [result["image_path"] for result in results] == paths
    assert [result["vehicle_count"] for result in results] == [1, 1]
    assert [result["detections"][0]["label"] for result in results] == ["car", "bus"]
    assert results[0]["model_name"] == "resnet18_trafficcamnet_pruned.onnx"
    assert results[0]["backend"] == "trafficcamnet"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "schema_version": 1,
                "backend": "trafficcamnet",
                "model": "model",
                "camera_id": "camera-7",
                "frames": [_frame_response(1), _frame_response(0)],
            },
            "order mismatch",
        ),
        (
            {
                "schema_version": 1,
                "backend": "trafficcamnet",
                "model": "model",
                "camera_id": "camera-7",
                "frames": [_frame_response(0)],
            },
            "frame count",
        ),
        (
            {
                "schema_version": 1,
                "backend": "trafficcamnet",
                "model": "model",
                "camera_id": "camera-7",
                "frames": [
                    {
                        "frame_index": 0,
                        "detections": [
                            {
                                "label": "car",
                                "confidence": 0.75,
                                "box": {"xmin": 10, "ymin": 10, "xmax": 5, "ymax": 20},
                            }
                        ],
                    },
                    _frame_response(1),
                ],
            },
            "empty box",
        ),
    ],
)
def test_analyze_burst_rejects_invalid_service_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    message: str,
) -> None:
    monkeypatch.setattr(
        "trafficcam.vision.trafficcamnet_client.urlopen",
        lambda *_args, **_kwargs: FakeResponse(payload),
    )
    client = TrafficCamNetClient()

    with pytest.raises(TrafficCamNetClientError, match=message):
        client.analyze_burst(_write_jpegs(tmp_path), camera_id="camera-7")


def test_analyze_burst_rejects_non_jpeg_before_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = tmp_path / "not-a-jpeg.jpg"
    image.write_bytes(b"not a jpeg")
    monkeypatch.setattr(
        "trafficcam.vision.trafficcamnet_client.urlopen",
        lambda *_args, **_kwargs: pytest.fail("service must not be called"),
    )

    with pytest.raises(ValueError, match="not a JPEG"):
        TrafficCamNetClient().analyze_burst([str(image)], camera_id="camera-7")


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (URLError("offline"), "service request failed"),
        (TimeoutError("slow response"), "service request timed out"),
    ],
)
def test_analyze_burst_surfaces_service_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    message: str,
) -> None:
    def fail_request(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(
        "trafficcam.vision.trafficcamnet_client.urlopen",
        fail_request,
    )

    with pytest.raises(TrafficCamNetClientError, match=message):
        TrafficCamNetClient().analyze_burst(_write_jpegs(tmp_path, 1), camera_id="camera-7")


def test_analyze_burst_rejects_empty_or_oversized_burst(tmp_path: Path) -> None:
    client = TrafficCamNetClient(max_burst_frames=1)
    with pytest.raises(ValueError, match="at least one"):
        client.analyze_burst([], camera_id="camera-7")
    with pytest.raises(ValueError, match="limit is 1"):
        client.analyze_burst(_write_jpegs(tmp_path), camera_id="camera-7")


def test_analyze_burst_requires_camera_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires a camera_id"):
        TrafficCamNetClient().analyze_burst(_write_jpegs(tmp_path, 1))
