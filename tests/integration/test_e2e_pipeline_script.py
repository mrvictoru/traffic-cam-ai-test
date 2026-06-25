import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_e2e_pipeline import run_pipeline


def _mock_detector():
    """Return a mock ZeroShotDetector that returns deterministic results."""
    mock = MagicMock()
    mock.analyze.return_value = {
        "image_path": "",
        "label": "moderate",
        "confidence": 0.75,
        "detections": [
            {"label": "car", "confidence": 0.8, "box": {"xmin": 10, "ymin": 10, "xmax": 50, "ymax": 40}},
            {"label": "car", "confidence": 0.7, "box": {"xmin": 60, "ymin": 10, "xmax": 100, "ymax": 40}},
        ],
        "vehicle_count": 2,
    }
    return mock


def _mock_scene_classifier():
    """Return a mock SceneClassifier that returns deterministic results."""
    mock = MagicMock()
    mock.classify.return_value = {
        "image_path": "",
        "scene": "day",
        "lighting": "day",
        "visibility": "clear",
        "confidence": 0.9,
        "heuristics": {"brightness": 150.0, "contrast": 30.0, "edge_density": 0.1},
        "quality_flag": "good",
        "zero_shot_labels": {},
    }
    return mock


def _create_synthetic_frames(output_dir: Path, count: int = 3) -> list[str]:
    """Create simple synthetic test images for the pipeline."""
    try:
        import cv2
        import numpy as np
    except Exception:
        pytest.skip("opencv or numpy not available for synthetic frame creation")

    frames_dir = output_dir / "fixtures"
    frames_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(count):
        # Create a gradient image (simulating a road scene)
        img = np.zeros((240, 320, 3), dtype=np.uint8)
        # Road-like gray background
        img[:, :] = (80, 80, 80)
        # Add some "vehicles" as colored rectangles
        for j in range(i + 2):
            x = 30 + j * 60
            y = 100 + (j % 2) * 40
            cv2.rectangle(img, (x, y), (x + 40, y + 30), (0, 0, 200), -1)
        path = frames_dir / f"frame_{i:03d}.jpg"
        cv2.imwrite(str(path), img)
        paths.append(str(path))
    return paths


def test_run_pipeline_persists_analysis_and_incidents(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Test Camera",
                        "detail_url": "https://example.test/cam/1001",
                        "stream_urls": ["https://example.test/stream.m3u8"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Create synthetic frames that will be "captured" by the mock
    fixture_frames = _create_synthetic_frames(tmp_path)

    # Mock ffmpeg: copy fixture frames to the expected output location
    def mock_ffmpeg(*args, **kwargs):
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            import shutil
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] >= 1
    assert result["camera_ids"] == ["1001"]
    assert (tmp_path / "data" / "analyses" / "1001").exists()


def test_run_pipeline_periodic_creates_multiple_records(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Test Camera",
                        "detail_url": "https://example.test/cam/1001",
                        "stream_urls": ["https://example.test/stream.m3u8"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fixture_frames = _create_synthetic_frames(tmp_path)

    def mock_ffmpeg(*args, **kwargs):
        import subprocess
        import shutil

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        # Clear previous frames to simulate fresh capture each cycle
        for existing in camera_output_dir.glob("frame_*.jpg"):
            existing.unlink()
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
            interval=0.0,
            max_cycles=3,
        )

    assert result["cycles_completed"] == 3
    assert result["analysis_count"] == 3
    # Trend analysis needs min_history records; 3 cycles may not trigger incidents
    # but the records should be persisted
    assert (tmp_path / "data" / "analyses" / "1001").exists()
    analysis_files = list((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    assert len(analysis_files) >= 3
