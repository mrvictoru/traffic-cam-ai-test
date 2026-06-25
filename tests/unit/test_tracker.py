"""Tests for the simple IoU-based tracker."""

from __future__ import annotations

from trafficcam.vision.tracker import SimpleTracker, _iou


class TestIoU:
    def test_identical_boxes(self) -> None:
        box = {"xmin": 10.0, "ymin": 10.0, "xmax": 20.0, "ymax": 20.0}
        assert _iou(box, box) == 1.0

    def test_no_overlap(self) -> None:
        a = {"xmin": 0.0, "ymin": 0.0, "xmax": 10.0, "ymax": 10.0}
        b = {"xmin": 20.0, "ymin": 20.0, "xmax": 30.0, "ymax": 30.0}
        assert _iou(a, b) == 0.0

    def test_partial_overlap(self) -> None:
        a = {"xmin": 0.0, "ymin": 0.0, "xmax": 10.0, "ymax": 10.0}
        b = {"xmin": 5.0, "ymin": 5.0, "xmax": 15.0, "ymax": 15.0}
        iou = _iou(a, b)
        # Intersection = 5x5 = 25, Union = 100+100-25 = 175
        assert iou == 25.0 / 175.0


class TestSimpleTracker:
    def test_tracks_single_detection(self) -> None:
        tracker = SimpleTracker(iou_threshold=0.3, max_age=2)
        dets = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 10.0, "ymin": 10.0, "xmax": 20.0, "ymax": 20.0},
            }
        ]
        tracks = tracker.update(dets)
        assert len(tracks) == 1
        assert tracks[1]["label"] == "car"
        assert len(tracks[1]["trajectory"]) == 1

    def test_matches_detection_to_existing_track(self) -> None:
        tracker = SimpleTracker(iou_threshold=0.3, max_age=2)
        dets1 = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 10.0, "ymin": 10.0, "xmax": 20.0, "ymax": 20.0},
            }
        ]
        tracker.update(dets1)

        dets2 = [
            {
                "label": "car",
                "confidence": 0.85,
                "box": {"xmin": 11.0, "ymin": 11.0, "xmax": 21.0, "ymax": 21.0},
            }
        ]
        tracks = tracker.update(dets2)
        assert len(tracks) == 1
        assert tracks[1]["trajectory"][-1] == (16.0, 16.0)

    def test_creates_new_track_when_iou_too_low(self) -> None:
        tracker = SimpleTracker(iou_threshold=0.3, max_age=2)
        dets1 = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 0.0, "ymin": 0.0, "xmax": 10.0, "ymax": 10.0},
            }
        ]
        tracker.update(dets1)

        dets2 = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 100.0, "ymin": 100.0, "xmax": 110.0, "ymax": 110.0},
            }
        ]
        tracks = tracker.update(dets2)
        assert len(tracks) == 2
        assert 1 in tracks
        assert 2 in tracks

    def test_ages_out_missing_tracks(self) -> None:
        tracker = SimpleTracker(iou_threshold=0.3, max_age=1)
        dets = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 10.0, "ymin": 10.0, "xmax": 20.0, "ymax": 20.0},
            }
        ]
        tracker.update(dets)
        tracks = tracker.update([])  # No detections -> age by 1
        assert len(tracks) == 1  # Still within max_age=1
        tracks = tracker.update([])  # Age by 1 more -> exceeds max_age
        assert len(tracks) == 0

    def test_reset_clears_tracks(self) -> None:
        tracker = SimpleTracker()
        dets = [
            {
                "label": "car",
                "confidence": 0.9,
                "box": {"xmin": 10.0, "ymin": 10.0, "xmax": 20.0, "ymax": 20.0},
            }
        ]
        tracker.update(dets)
        assert tracker.active_count == 1
        tracker.reset()
        assert tracker.active_count == 0
