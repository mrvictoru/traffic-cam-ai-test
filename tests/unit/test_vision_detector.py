"""Tests for the zero-shot vision detector."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from trafficcam.vision import ZeroShotDetector
from trafficcam.vision.density_scorer import DensityScorer


class TestDensityScorer:
    def test_from_count_light(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.from_count(2) == "light"
        assert scorer.from_count(0) == "light"

    def test_from_count_moderate(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.from_count(5) == "moderate"
        assert scorer.from_count(14) == "moderate"

    def test_from_count_heavy(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.from_count(15) == "heavy"
        assert scorer.from_count(29) == "heavy"

    def test_from_count_blocked(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.from_count(30) == "blocked"
        assert scorer.from_count(100) == "blocked"

    def test_from_coverage(self) -> None:
        scorer = DensityScorer()
        assert scorer.from_coverage(0.05) == "light"
        assert scorer.from_coverage(0.15) == "moderate"
        assert scorer.from_coverage(0.45) == "heavy"
        assert scorer.from_coverage(0.75) == "blocked"


class TestZeroShotDetectorFallback:
    """Tests for ZeroShotDetector that don't require the model to be loaded."""

    def test_init_without_transformers_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.detector._TRANSFORMERS_AVAILABLE", False
        )
        with pytest.raises(RuntimeError, match="transformers is required"):
            ZeroShotDetector()

    def test_init_without_ultralytics_raises_for_yolo_backend(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.detector._ULTRALYTICS_AVAILABLE", False
        )
        with pytest.raises(RuntimeError, match="ultralytics is required"):
            ZeroShotDetector(backend="yolo")

    def test_invalid_backend_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported vision backend"):
            ZeroShotDetector(backend="unknown")

    def test_resolve_yolo_model_source_prefers_cached_weight(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.detector._ULTRALYTICS_AVAILABLE", True
        )
        cached_dir = tmp_path / "weights"
        cached_dir.mkdir(parents=True, exist_ok=True)
        cached_weight = cached_dir / "yolov8n.pt"
        cached_weight.write_bytes(b"cached")

        detector = ZeroShotDetector(backend="yolo", model_name="yolov8n.pt")
        monkeypatch.setattr(
            "trafficcam.vision.detector.settings",
            SimpleNamespace(vision_yolo_weights_dir=str(cached_dir)),
        )

        assert detector._resolve_yolo_model_source() == str(cached_weight)
    def test_resolve_yolo_model_source_prefers_cache_over_repo_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.detector._ULTRALYTICS_AVAILABLE", True
        )
        cached_dir = tmp_path / "weights"
        cached_dir.mkdir(parents=True, exist_ok=True)
        cached_weight = cached_dir / "yolov8n.pt"
        cached_weight.write_bytes(b"cached")

        repo_weight = tmp_path / "yolov8n.pt"
        repo_weight.write_bytes(b"repo")

        detector = ZeroShotDetector(backend="yolo", model_name=str(repo_weight))
        monkeypatch.setattr(
            "trafficcam.vision.detector.settings",
            SimpleNamespace(vision_yolo_weights_dir=str(cached_dir)),
        )

        assert detector._resolve_yolo_model_source() == str(cached_weight)
