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

    def test_from_count_uses_camera_specific_thresholds_when_available(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        config_path = tmp_path / "camera_density_thresholds.json"
        config_path.write_text(
            """
            {
              "cameras": {
                "49": {"light": 3, "moderate": 8, "heavy": 12}
              }
            }
            """.strip(),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "trafficcam.vision.density_scorer.settings",
            SimpleNamespace(
                density_threshold_light=5,
                density_threshold_moderate=15,
                density_threshold_heavy=30,
                camera_density_thresholds_path=str(config_path),
            ),
        )

        scorer = DensityScorer(camera_id="49")
        assert scorer.from_count(2) == "light"
        assert scorer.from_count(3) == "moderate"
        assert scorer.from_count(8) == "heavy"
        assert scorer.from_count(12) == "blocked"

    def test_from_count_falls_back_to_global_when_camera_thresholds_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.density_scorer.settings",
            SimpleNamespace(
                density_threshold_light=5,
                density_threshold_moderate=15,
                density_threshold_heavy=30,
                camera_density_thresholds_path="config/does-not-exist.json",
            ),
        )

        scorer = DensityScorer(camera_id="49")
        assert scorer.from_count(4) == "light"
        assert scorer.from_count(5) == "moderate"


class TestCongestionScore:
    """Hybrid continuous congestion scoring (coverage + count + confidence)."""

    def test_score_zero_when_no_vehicles(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.score(coverage_ratio=0.0, count=0, mean_confidence=0.8) == 0.0
        assert scorer.score(count=0) == 0.0

    def test_score_is_monotonic_in_count(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        scores = [scorer.score(count=n, mean_confidence=0.7) for n in (2, 8, 20, 40)]
        assert scores == sorted(scores)

    def test_score_coverage_raises_score(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        low = scorer.score(coverage_ratio=0.1, count=10, mean_confidence=0.7)
        high = scorer.score(coverage_ratio=0.4, count=10, mean_confidence=0.7)
        assert high > low

    def test_score_low_confidence_discounts(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        trusted = scorer.score(count=20, mean_confidence=0.9)
        noisy = scorer.score(count=20, mean_confidence=0.2)
        assert noisy < trusted

    def test_score_low_confidence_discounts_quadratically(self) -> None:
        # Regression: a storm of low-confidence detections (e.g. 94 boxes at
        # conf 0.24) must not read as "blocked". Below full-trust confidence
        # the discount is quadratic, so noisy detections contribute very little.
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        noisy_score = scorer.score(coverage_ratio=0.5, count=40, mean_confidence=0.24)
        assert scorer.label_from_score(noisy_score) != "blocked"
        assert noisy_score < 50.0

    def test_score_bounded_0_100(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        assert scorer.score(coverage_ratio=1.0, count=999, mean_confidence=1.0) <= 100.0
        assert scorer.score(coverage_ratio=0.0, count=-5, mean_confidence=0.0) >= 0.0

    def test_label_from_score_boundaries(self) -> None:
        assert DensityScorer.label_from_score(10.0) == "light"
        assert DensityScorer.label_from_score(25.0) == "moderate"
        assert DensityScorer.label_from_score(50.0) == "heavy"
        assert DensityScorer.label_from_score(75.0) == "blocked"

    def test_score_without_coverage_uses_count_only(self) -> None:
        scorer = DensityScorer(light=5, moderate=15, heavy=30)
        # No coverage signal: full weight goes to the count component.
        assert scorer.score(count=30, mean_confidence=0.6) == 100.0


class TestComputeCoverageRatio:
    """Rasterized ROI coverage of vehicle boxes."""

    def _box(self, xmin: float, ymin: float, xmax: float, ymax: float) -> dict:
        return {"box": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}}

    def test_empty_detections_have_zero_coverage(self) -> None:
        from trafficcam.vision.roi import compute_coverage_ratio

        assert compute_coverage_ratio([], None, 320, 240) == 0.0

    def test_full_frame_single_region(self) -> None:
        from trafficcam.vision.roi import compute_coverage_ratio

        ratio = compute_coverage_ratio(
            [self._box(0, 0, 160, 240)], None, 320, 240
        )
        assert ratio == pytest.approx(0.5, abs=0.01)

    def test_boxes_outside_roi_are_excluded(self) -> None:
        from trafficcam.vision.roi import compute_coverage_ratio

        roi = [[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]]  # right half
        ratio_left = compute_coverage_ratio([self._box(0, 0, 100, 200)], roi, 320, 240)
        ratio_right = compute_coverage_ratio([self._box(170, 0, 300, 200)], roi, 320, 240)
        assert ratio_left < 0.05
        assert ratio_right > ratio_left * 5

    def test_overlapping_boxes_do_not_double_count(self) -> None:
        from trafficcam.vision.roi import compute_coverage_ratio

        single = compute_coverage_ratio(
            [self._box(10, 10, 50, 40)] * 35, None, 320, 240
        )
        assert single < 0.1  # one 40x30 box in a 320x240 frame


class TestZeroShotDetectorFallback:
    """Tests for ZeroShotDetector that don't require the model to be loaded."""

    def test_init_without_transformers_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "trafficcam.vision.detector._TRANSFORMERS_AVAILABLE", False
        )
        # The default backend is yolo, which does not need transformers.
        with pytest.raises(RuntimeError, match="transformers is required"):
            ZeroShotDetector(backend="owlvit")

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
