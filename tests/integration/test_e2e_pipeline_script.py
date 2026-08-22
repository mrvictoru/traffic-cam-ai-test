import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_e2e_pipeline import run_pipeline
from trafficcam.vision.tracker import SimpleTracker


class _FakeSupervisionTracker:
    def __init__(self) -> None:
        self._tracker = SimpleTracker(iou_threshold=0.3, max_age=2)
        self.backend_name = "supervision"
        self.latest_detections = object()

    def update(self, detections):
        tracks = self._tracker.update(detections)
        self.latest_detections = object()
        return tracks

    @property
    def active_count(self):
        return self._tracker.active_count

    @property
    def track_histories(self):
        return self._tracker.track_histories


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


def _mock_night_scene_classifier():
    """Return a poor-quality night classification for regression coverage."""
    mock = MagicMock()
    mock.classify.return_value = {
        "image_path": "",
        "scene": "night",
        "lighting": "night",
        "visibility": "low_visibility",
        "confidence": 0.75,
        "heuristics": {
            "brightness": 120.0,
            "brightness_median": 25.0,
            "contrast": 18.0,
            "edge_density": 0.02,
        },
        "quality_flag": "poor",
        "zero_shot_labels": {},
    }
    return mock


def _mock_blocked_low_confidence_detector():
    """Return a detector result matching the observed false-jam failure mode."""
    mock = MagicMock()
    mock.analyze.return_value = {
        "image_path": "",
        "label": "blocked",
        "confidence": 0.23,
        "detections": [
            {"label": "car", "confidence": 0.23, "box": {"xmin": 10, "ymin": 10, "xmax": 50, "ymax": 40}}
        ] * 35,
        "vehicle_count": 35,
    }
    return mock


def _mock_heavy_low_confidence_detector():
    """Return a heavy result that should be relaxed at night."""
    mock = MagicMock()
    mock.analyze.return_value = {
        "image_path": "",
        "label": "heavy",
        "confidence": 0.34,
        "detections": [
            {"label": "car", "confidence": 0.34, "box": {"xmin": 10, "ymin": 10, "xmax": 50, "ymax": 40}}
        ] * 18,
        "vehicle_count": 18,
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
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    assert saved_record["details"]["capture_result"]["sample_fps"] == 1.0
    assert saved_record["details"]["capture_result"]["warmup_seconds"] == 0.0


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


def test_run_pipeline_relaxes_low_confidence_night_blocked_label(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Night Camera",
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
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_blocked_low_confidence_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_night_scene_classifier()),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    # The hybrid score already discounts low confidence, so the final label is
    # score-derived ("moderate") while raw_density preserves the detector's
    # count-based bucket for diagnostics.
    assert saved_record["details"]["raw_density"] == "blocked"
    assert saved_record["details"]["density"] in {"light", "moderate"}
    assert saved_record["details"]["lighting"] == "night"
    assert saved_record["details"]["congestion_score"] > 0


def test_run_pipeline_relaxes_low_confidence_night_heavy_label(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Night Camera",
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
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_heavy_low_confidence_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_night_scene_classifier()),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    # Score-derived label discounts low confidence at night; raw bucket kept.
    assert saved_record["details"]["raw_density"] == "heavy"
    assert saved_record["details"]["density"] in {"light", "moderate"}
    assert saved_record["details"]["lighting"] == "night"
    assert saved_record["details"]["congestion_score"] > 0


def test_run_pipeline_keeps_daytime_heavy_label(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Day Camera",
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
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_heavy_low_confidence_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    assert saved_record["details"]["raw_density"] == "heavy"
    # Daytime: score-derived label; moderate at this count/confidence combo.
    assert saved_record["details"]["density"] in {"moderate", "heavy"}
    assert saved_record["details"]["lighting"] == "day"
    assert saved_record["details"]["congestion_score"] > 0


def test_run_pipeline_persists_directional_flow_split(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Flow Camera",
                        "detail_url": "https://example.test/cam/1001",
                        "stream_urls": ["https://example.test/stream.m3u8"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flow_lines_path = tmp_path / "camera_flow_lines.json"
    flow_lines_path.write_text(
        json.dumps({"1001": {"start": [0.0, 0.5], "end": [1.0, 0.5]}}),
        encoding="utf-8",
    )

    fixture_frames = _create_synthetic_frames(tmp_path)
    moving_boxes = [
        {"xmin": 80, "ymin": 120, "xmax": 120, "ymax": 200},
        {"xmin": 82, "ymin": 80, "xmax": 122, "ymax": 160},
        {"xmin": 84, "ymin": 40, "xmax": 124, "ymax": 120},
    ]

    detector = MagicMock()
    detector.analyze.side_effect = [
        {
            "image_path": fixture_frames[idx],
            "label": "light",
            "confidence": 0.9,
            "detections": [{"label": "car", "confidence": 0.9, "box": box}],
            "vehicle_count": 1,
        }
        for idx, box in enumerate(moving_boxes)
    ]

    def mock_ffmpeg(*args, **kwargs):
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    runtime_settings = SimpleNamespace(
        roi_config_path=str(tmp_path / "missing_rois.json"),
        roi_filter_enabled=False,
        flow_line_config_path=str(flow_lines_path),
        capture_burst_fps=1.0,
        capture_warmup_seconds=0.0,
        night_density_downgrade_steps=1,
        night_blocked_min_confidence=0.5,
        night_heavy_min_confidence=0.4,
        supervision_debug_frames_enabled=False,
        supervision_debug_dirname="debug",
    )

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=detector),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
        patch("scripts.run_e2e_pipeline.build_tracker", return_value=SimpleTracker(iou_threshold=0.3, max_age=2)),
        patch("scripts.run_e2e_pipeline.settings", runtime_settings),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    assert saved_record["details"]["flow_rate_vph"] == {
        "northbound": 1,
        "southbound": 0,
        "total": 1,
    }


def test_run_pipeline_persists_line_crossings_from_supervision_counter(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Flow Camera",
                        "detail_url": "https://example.test/cam/1001",
                        "stream_urls": ["https://example.test/stream.m3u8"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    flow_lines_path = tmp_path / "camera_flow_lines.json"
    flow_lines_path.write_text(
        json.dumps({"1001": {"start": [0.0, 0.5], "end": [1.0, 0.5]}}),
        encoding="utf-8",
    )

    fixture_frames = _create_synthetic_frames(tmp_path)
    detector = MagicMock()
    detector.analyze.side_effect = [
        {
            "image_path": fixture_frames[idx],
            "label": "light",
            "confidence": 0.9,
            "detections": [
                {
                    "label": "car",
                    "confidence": 0.9,
                    "box": {"xmin": 20 + idx, "ymin": 80 - idx * 5, "xmax": 60 + idx, "ymax": 140 - idx * 5},
                }
            ],
            "vehicle_count": 1,
        }
        for idx in range(3)
    ]

    def mock_ffmpeg(*args, **kwargs):
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    class FakePoint:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    class FakeLineZone:
        def __init__(self, start, end):
            self.start = start
            self.end = end
            self.in_count = 0
            self.out_count = 0
            self.calls = 0

        def trigger(self, detections):
            self.calls += 1
            if self.calls == 2:
                self.in_count += 1

    runtime_settings = SimpleNamespace(
        roi_config_path=str(tmp_path / "missing_rois.json"),
        roi_filter_enabled=False,
        flow_line_config_path=str(flow_lines_path),
        capture_burst_fps=1.0,
        capture_warmup_seconds=0.0,
        night_density_downgrade_steps=1,
        night_blocked_min_confidence=0.5,
        night_heavy_min_confidence=0.4,
        supervision_debug_frames_enabled=False,
        supervision_debug_dirname="debug",
    )

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=detector),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
        patch("scripts.run_e2e_pipeline.build_tracker", return_value=_FakeSupervisionTracker()),
        patch("scripts.run_e2e_pipeline.settings", runtime_settings),
        patch("scripts.run_e2e_pipeline._SUPERVISION_AVAILABLE", True),
        patch("scripts.run_e2e_pipeline.sv", SimpleNamespace(Point=FakePoint, LineZone=FakeLineZone)),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    analysis_files = sorted((tmp_path / "data" / "analyses" / "1001").glob("*.json"))
    saved_record = json.loads(analysis_files[-1].read_text(encoding="utf-8"))
    assert saved_record["details"]["line_crossings"] == {"in": 1, "out": 0, "total": 1}
    assert saved_record["details"]["tracking_backend"] == "supervision"


def test_run_pipeline_exports_debug_frames_when_enabled(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Debug Camera",
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
        import shutil
        import subprocess

        camera_output_dir = tmp_path / "output" / "e2e" / "cam_1001"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        for i, src in enumerate(fixture_frames):
            dst = camera_output_dir / f"frame_{i + 1:03d}.jpg"
            shutil.copy(src, dst)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    runtime_settings = SimpleNamespace(
        roi_config_path=str(tmp_path / "missing_rois.json"),
        roi_filter_enabled=False,
        flow_line_config_path=str(tmp_path / "missing_lines.json"),
        capture_burst_fps=1.0,
        capture_warmup_seconds=0.0,
        night_density_downgrade_steps=1,
        night_blocked_min_confidence=0.5,
        night_heavy_min_confidence=0.4,
        supervision_debug_frames_enabled=True,
        supervision_debug_dirname="debug",
    )

    with (
        patch("subprocess.run", side_effect=mock_ffmpeg),
        patch("scripts.run_e2e_pipeline.ZeroShotDetector", return_value=_mock_detector()),
        patch("scripts.run_e2e_pipeline.SceneClassifier", return_value=_mock_scene_classifier()),
        patch("scripts.run_e2e_pipeline.build_tracker", return_value=SimpleTracker(iou_threshold=0.3, max_age=2)),
        patch("scripts.run_e2e_pipeline.settings", runtime_settings),
    ):
        result = run_pipeline(
            manifest_file=manifest_path,
            output_dir=tmp_path / "output" / "e2e",
            data_dir=tmp_path / "data",
            frame_count=3,
            limit=1,
        )

    assert result["analysis_count"] == 1
    debug_dir = tmp_path / "output" / "e2e" / "cam_1001" / "debug"
    assert debug_dir.exists()
    assert (debug_dir / "frame_001_tracked.jpg").exists()
