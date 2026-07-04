"""Simple IoU-based tracker for associating detections across frames."""

from __future__ import annotations

from typing import Any

from trafficcam.config import settings


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

    def update(self, detections: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        """Update tracks with new detections and return the current active tracks.

        Args:
            detections: List of detection dicts from ZeroShotDetector, each with
                ``box`` and ``confidence`` keys.

        Returns:
            Mapping of track_id -> track info (box, confidence, age, trajectory).
        """
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
                track["trajectory"].append(_box_centroid(box))
                new_tracks[best_track_id] = track
                assigned.add(best_track_id)
            else:
                # Create new track
                track_id = self._next_id
                self._next_id += 1
                new_tracks[track_id] = {
                    "track_id": track_id,
                    "box": box,
                    "confidence": det["confidence"],
                    "label": det.get("label", "unknown"),
                    "age": 0,
                    "trajectory": [_box_centroid(box)],
                }

        # Age out unassigned tracks
        for track_id, track in self._tracks.items():
            if track_id not in assigned:
                track["age"] += 1
                if track["age"] <= self.max_age:
                    new_tracks[track_id] = track

        self._tracks = new_tracks
        return dict(self._tracks)

    def reset(self) -> None:
        """Clear all tracks."""
        self._tracks.clear()
        self._next_id = 1

    @property
    def active_count(self) -> int:
        """Number of currently active tracks."""
        return len(self._tracks)
