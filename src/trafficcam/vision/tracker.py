"""Simple IoU-based tracker for associating detections across frames."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from trafficcam.config import settings

LOGGER = logging.getLogger(__name__)

try:
    import supervision as sv

    _SUPERVISION_AVAILABLE = True
except Exception:  # pragma: no cover
    _SUPERVISION_AVAILABLE = False


def _iou(box_a: dict[str, float], box_b: dict[str, float]) -> float:
    """Compute intersection-over-union for two boxes in {xmin, ymin, xmax, ymax} format."""
    xa = max(box_a["xmin"], box_b["xmin"])
    ya = max(box_a["ymin"], box_b["ymin"])
    xb = min(box_a["xmax"], box_b["xmax"])
    yb = min(box_a["ymax"], box_b["ymax"])

    inter_w = max(0.0, xb - xa)
    inter_h = max(0.0, yb - ya)
    inter_area = inter_w * inter_h

    area_a = (box_a["xmax"] - box_a["xmin"]) * (box_a["ymax"] - box_a["ymin"])
    area_b = (box_b["xmax"] - box_b["xmin"]) * (box_b["ymax"] - box_b["ymin"])
    union_area = area_a + area_b - inter_area

    return inter_area / union_area if union_area > 0 else 0.0


def _box_centroid(box: dict[str, float]) -> tuple[float, float]:
    """Return the centroid of a bounding box."""
    cx = (box["xmin"] + box["xmax"]) / 2.0
    cy = (box["ymin"] + box["ymax"]) / 2.0
    return cx, cy


def _append_track_history(
    histories: dict[int, list[tuple[int, int, tuple[float, float]]]],
    track_id: int,
    frame_index: int,
    box: dict[str, float],
) -> tuple[float, float]:
    centroid = _box_centroid(box)
    histories.setdefault(track_id, []).append((track_id, frame_index, centroid))
    return centroid


def _empty_supervision_detections() -> Any:
    return sv.Detections(
        xyxy=np.empty((0, 4), dtype=np.float32),
        confidence=np.empty((0,), dtype=np.float32),
        class_id=np.empty((0,), dtype=np.int32),
    )


def _to_supervision_detections(detections: list[dict[str, Any]]) -> Any:
    if not detections:
        return _empty_supervision_detections()

    xyxy = np.array(
        [
            [
                float(det["box"]["xmin"]),
                float(det["box"]["ymin"]),
                float(det["box"]["xmax"]),
                float(det["box"]["ymax"]),
            ]
            for det in detections
        ],
        dtype=np.float32,
    )
    confidence = np.array(
        [float(det.get("confidence", 0.0)) for det in detections],
        dtype=np.float32,
    )
    class_id = np.zeros((len(detections),), dtype=np.int32)
    return sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)


def _tracks_to_supervision_detections(tracks: dict[int, dict[str, Any]]) -> Any | None:
    if not _SUPERVISION_AVAILABLE:
        return None
    if not tracks:
        return _empty_supervision_detections()

    ordered_tracks = sorted(tracks.items())
    xyxy = np.array(
        [
            [
                float(track["box"]["xmin"]),
                float(track["box"]["ymin"]),
                float(track["box"]["xmax"]),
                float(track["box"]["ymax"]),
            ]
            for _, track in ordered_tracks
        ],
        dtype=np.float32,
    )
    confidence = np.array(
        [float(track.get("confidence", 0.0)) for _, track in ordered_tracks],
        dtype=np.float32,
    )
    class_id = np.zeros((len(ordered_tracks),), dtype=np.int32)
    tracker_id = np.array([track_id for track_id, _ in ordered_tracks], dtype=np.int32)
    return sv.Detections(
        xyxy=xyxy,
        confidence=confidence,
        class_id=class_id,
        tracker_id=tracker_id,
    )


class SimpleTracker:
    """IoU-based tracker that maintains vehicle identities across frames.

    Associates detections frame-to-frame using Intersection-over-Union.
    Tracks that disappear for more than ``max_age`` frames are dropped.
    """

    def __init__(
        self,
        iou_threshold: float | None = None,
        max_age: int | None = None,
    ) -> None:
        self.iou_threshold = (
            iou_threshold if iou_threshold is not None else settings.tracker_iou_threshold
        )
        self.max_age = max_age if max_age is not None else settings.tracker_max_age
        self._next_id: int = 1
        self._tracks: dict[int, dict[str, Any]] = {}
        self._frame_index: int = 0
        self._track_histories: dict[int, list[tuple[int, int, tuple[float, float]]]] = {}
        self._latest_detections: Any | None = None

    def update(self, detections: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Update tracks with new detections and return the current active tracks.

        Args:
            detections: List of detection dicts from ZeroShotDetector, each with
                ``box`` and ``confidence`` keys.

        Returns:
            Mapping of track_id -> track info (box, confidence, age, trajectory).
        """
        frame_index = self._frame_index
        assigned: set[int] = set()
        new_tracks: dict[int, dict[str, Any]] = {}

        # Try to match each detection to an existing track
        for det in detections:
            box = det["box"]
            best_iou = 0.0
            best_track_id: int | None = None

            for track_id, track in self._tracks.items():
                if track_id in assigned:
                    continue
                iou = _iou(box, track["box"])
                if iou > best_iou:
                    best_iou = iou
                    best_track_id = track_id

            if best_track_id is not None and best_iou >= self.iou_threshold:
                # Update existing track
                track = self._tracks[best_track_id]
                track["box"] = box
                track["confidence"] = det["confidence"]
                track["age"] = 0
                track["trajectory"].append(
                    _append_track_history(
                        self._track_histories,
                        best_track_id,
                        frame_index,
                        box,
                    )
                )
                new_tracks[best_track_id] = track
                assigned.add(best_track_id)
            else:
                # Create new track
                track_id = self._next_id
                self._next_id += 1
                centroid = _append_track_history(
                    self._track_histories,
                    track_id,
                    frame_index,
                    box,
                )
                new_tracks[track_id] = {
                    "track_id": track_id,
                    "box": box,
                    "confidence": det["confidence"],
                    "label": det.get("label", "unknown"),
                    "age": 0,
                    "trajectory": [centroid],
                }

        # Age out unassigned tracks
        for track_id, track in self._tracks.items():
            if track_id not in assigned:
                track["age"] += 1
                if track["age"] <= self.max_age:
                    new_tracks[track_id] = track

        self._tracks = new_tracks
        self._latest_detections = _tracks_to_supervision_detections(self._tracks)
        self._frame_index += 1
        return dict(self._tracks)

    def reset(self) -> None:
        """Clear all tracks."""
        self._tracks.clear()
        self._track_histories.clear()
        self._latest_detections = None
        self._frame_index = 0
        self._next_id = 1

    @property
    def active_count(self) -> int:
        """Number of currently active tracks."""
        return len(self._tracks)

    @property
    def track_histories(self) -> list[list[tuple[int, int, tuple[float, float]]]]:
        """All observed trajectories across the current burst."""
        return list(self._track_histories.values())

    @property
    def latest_detections(self) -> Any | None:
        return self._latest_detections

    @property
    def backend_name(self) -> str:
        return "simple"


class SupervisionTracker:
    """ByteTrack-backed tracker used when Supervision is available."""

    def __init__(self, frame_rate: float | None = None) -> None:
        if not _SUPERVISION_AVAILABLE:
            raise RuntimeError(
                "supervision is required for the supervision tracker backend. "
                "Install it with: pip install supervision"
            )

        self._tracker = sv.ByteTrack(
            track_activation_threshold=settings.supervision_track_activation_threshold,
            lost_track_buffer=settings.supervision_lost_track_buffer,
            minimum_matching_threshold=settings.supervision_minimum_matching_threshold,
            frame_rate=frame_rate or 30.0,
            minimum_consecutive_frames=settings.supervision_minimum_consecutive_frames,
        )
        self._tracks: dict[int, dict[str, Any]] = {}
        self._track_histories: dict[int, list[tuple[int, int, tuple[float, float]]]] = {}
        self._frame_index = 0
        self._latest_detections: Any = _empty_supervision_detections()

    def update(self, detections: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        frame_index = self._frame_index
        tracked = self._tracker.update_with_detections(_to_supervision_detections(detections))
        xyxy = np.asarray(getattr(tracked, "xyxy", np.empty((0, 4), dtype=np.float32)))
        confidence = np.asarray(
            getattr(tracked, "confidence", np.zeros((len(xyxy),), dtype=np.float32))
        )
        tracker_ids = list(getattr(tracked, "tracker_id", []) or [])

        new_tracks: dict[int, dict[str, Any]] = {}
        for idx, box_values in enumerate(xyxy):
            raw_track_id = tracker_ids[idx] if idx < len(tracker_ids) else idx + 1
            track_id = int(raw_track_id)
            box = {
                "xmin": float(box_values[0]),
                "ymin": float(box_values[1]),
                "xmax": float(box_values[2]),
                "ymax": float(box_values[3]),
            }
            centroid = _append_track_history(
                self._track_histories,
                track_id,
                frame_index,
                box,
            )
            prior_track = self._tracks.get(track_id, {})
            trajectory = list(prior_track.get("trajectory", []))
            trajectory.append(centroid)
            new_tracks[track_id] = {
                "track_id": track_id,
                "box": box,
                "confidence": float(confidence[idx]) if idx < len(confidence) else 0.0,
                "label": (
                    detections[idx].get("label", prior_track.get("label", "vehicle"))
                    if idx < len(detections)
                    else prior_track.get("label", "vehicle")
                ),
                "age": 0,
                "trajectory": trajectory,
            }

        self._tracks = new_tracks
        self._latest_detections = tracked
        self._frame_index += 1
        return dict(self._tracks)

    def reset(self) -> None:
        self._tracker.reset()
        self._tracks.clear()
        self._track_histories.clear()
        self._latest_detections = _empty_supervision_detections()
        self._frame_index = 0

    @property
    def active_count(self) -> int:
        return len(self._tracks)

    @property
    def track_histories(self) -> list[list[tuple[int, int, tuple[float, float]]]]:
        return list(self._track_histories.values())

    @property
    def latest_detections(self) -> Any:
        return self._latest_detections

    @property
    def backend_name(self) -> str:
        return "supervision"


def build_tracker(frame_rate: float | None = None) -> SimpleTracker | SupervisionTracker:
    """Create the configured tracker, falling back to the simple tracker when needed."""
    backend = str(getattr(settings, "tracker_backend", "auto")).strip().lower()
    if backend not in {"simple", "supervision", "auto"}:
        raise ValueError(f"Unsupported tracker backend: {backend}")

    if backend in {"supervision", "auto"}:
        if _SUPERVISION_AVAILABLE:
            return SupervisionTracker(frame_rate=frame_rate)
        if backend == "supervision":
            LOGGER.warning("Supervision tracker requested but package is unavailable; falling back to SimpleTracker")

    return SimpleTracker()
