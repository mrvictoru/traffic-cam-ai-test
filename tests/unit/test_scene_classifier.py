"""Tests for the scene classifier."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from trafficcam.vision.scene import SceneClassifier


class TestSceneClassifierHeuristics:
    def test_classify_missing_file_raises(self) -> None:
        clf = SceneClassifier(use_zero_shot=False)
        with pytest.raises(FileNotFoundError):
            clf.classify("/nonexistent/image.jpg")

    def test_classify_synthetic_bright_image(self, tmp_path: Path) -> None:
        # Create a bright synthetic image with texture so edges are detected
        img_path = tmp_path / "bright.png"
        img = np.full((100, 100, 3), 240, dtype=np.uint8)
        # Add a dark stripe to create edges (avoids zero edge density -> low_visibility)
        img[40:60, :] = 80

        try:
            import cv2
            cv2.imwrite(str(img_path), img)
        except Exception:
            pytest.skip("opencv not available")

        clf = SceneClassifier(
            brightness_day_min=110,
            brightness_dusk_min=60,
            use_zero_shot=False,
        )
        result = clf.classify(str(img_path))

        assert result["lighting"] == "day"
        assert result["heuristics"]["brightness"] > 110
        # quality_flag may be good or fair depending on edge density;
        # the important thing is lighting classification

    def test_classify_synthetic_dark_image(self, tmp_path: Path) -> None:
        # Create a dark synthetic image
        img_path = tmp_path / "dark.png"
        img = np.full((100, 100, 3), 20, dtype=np.uint8)
        # Add a lighter stripe for some edge structure
        img[40:60, :] = 60

        try:
            import cv2
            cv2.imwrite(str(img_path), img)
        except Exception:
            pytest.skip("opencv not available")

        clf = SceneClassifier(
            brightness_day_min=110,
            brightness_dusk_min=60,
            use_zero_shot=False,
        )
        result = clf.classify(str(img_path))

        assert result["lighting"] == "night"
        assert result["heuristics"]["brightness"] < 60

    def test_classify_synthetic_dusk_image(self, tmp_path: Path) -> None:
        # Create a medium-brightness image with texture
        img_path = tmp_path / "dusk.png"
        img = np.full((100, 100, 3), 80, dtype=np.uint8)
        # Add a stripe to create edges
        img[40:60, :] = 120

        try:
            import cv2
            cv2.imwrite(str(img_path), img)
        except Exception:
            pytest.skip("opencv not available")

        clf = SceneClassifier(
            brightness_day_min=110,
            brightness_dusk_min=60,
            use_zero_shot=False,
        )
        result = clf.classify(str(img_path))

        assert result["lighting"] == "dusk"
        assert result["heuristics"]["brightness"] >= 60
        assert result["heuristics"]["brightness"] < 110
