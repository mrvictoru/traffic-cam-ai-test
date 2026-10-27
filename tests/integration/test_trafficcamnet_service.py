from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from scripts.run_e2e_pipeline import _analyze_burst
from trafficcam.config import settings
from trafficcam.vision import SceneClassifier, TrafficCamNetClient


@pytest.mark.skipif(
    os.getenv("RUN_TRAFFICCAMNET_INTEGRATION") != "1",
    reason="requires the healthy DeepStream TrafficCamNet Compose service",
)
def test_live_trafficcamnet_service_accepts_an_ordered_burst(tmp_path: Path) -> None:
    paths = []
    for index, color in enumerate(((40, 40, 40), (80, 80, 80), (120, 120, 120))):
        path = tmp_path / f"frame-{index}.jpg"
        Image.new("RGB", (352, 288), color).save(path, format="JPEG")
        paths.append(str(path))

    client = TrafficCamNetClient(
        service_url=settings.vision_trafficcamnet_url,
        timeout_seconds=settings.vision_trafficcamnet_timeout_seconds,
    )
    results = client.analyze_burst(paths, camera_id="integration-smoke")

    assert [result["image_path"] for result in results] == paths
    assert all(result["backend"] == "trafficcamnet" for result in results)
    assert all(result["model_name"] for result in results)
    assert all(result["vehicle_count"] == len(result["detections"]) for result in results)

    analysis = _analyze_burst(
        paths,
        camera_id="integration-smoke",
        capture_result={
            "status": "complete",
            "sample_fps": 5.0,
            "decoded_frame_count": len(paths),
        },
        data_dir=tmp_path,
        detector=client,
        scene_classifier=SceneClassifier(use_zero_shot=False),
    )
    assert analysis["health"]["analysis"]["status"] == "ok"
    assert analysis["details"]["detector_backend"] == "trafficcamnet"
    assert analysis["details"]["frame_count"] == len(paths)
