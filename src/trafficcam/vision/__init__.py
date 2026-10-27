"""Vision package for AI-powered traffic analysis."""

from __future__ import annotations

from trafficcam.config import settings

from .detector import ZeroShotDetector
from .trafficcamnet_client import TrafficCamNetClient, TrafficCamNetClientError
from .density_scorer import DensityScorer
from .tracker import SimpleTracker, SupervisionTracker, build_tracker
from .scene import SceneClassifier
from .motion import MotionAssessment, classify_motion


def create_detector(backend: str | None = None):
    """Create the configured local or remote detector without backend fallback."""
    selected = (backend or settings.vision_backend).strip().lower()
    if selected == "trafficcamnet":
        from .trafficcamnet_client import TrafficCamNetClient

        return TrafficCamNetClient()
    return ZeroShotDetector(backend=selected)


__all__ = [
	"ZeroShotDetector",
	"create_detector",
	"TrafficCamNetClient",
	"TrafficCamNetClientError",
	"DensityScorer",
	"SimpleTracker",
	"SupervisionTracker",
	"build_tracker",
	"SceneClassifier",
	"MotionAssessment",
	"classify_motion",
]
