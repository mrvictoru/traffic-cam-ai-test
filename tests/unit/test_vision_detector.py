"""Tests for the zero-shot vision detector."""

from __future__ import annotations

from pathlib import Path

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
