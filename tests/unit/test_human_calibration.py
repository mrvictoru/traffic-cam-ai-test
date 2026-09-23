from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from trafficcam.calibration import build_human_calibration, offpeak_window_status


def test_offpeak_window_is_closed_in_the_evening() -> None:
    now = datetime(2026, 8, 28, 22, 54, tzinfo=ZoneInfo("Asia/Macau"))
    status = offpeak_window_status(now)

    assert status["in_offpeak_window"] is False
    assert status["can_collect_freeflow_samples"] is False
    assert status["offpeak_hours"] == "02:00-05:00"
    assert status["minutes_until_next_window"] == 186
    assert status["next_window_start"].startswith("2026-08-29T02:00:00")


def test_offpeak_window_is_open_at_three_am() -> None:
    now = datetime(2026, 8, 29, 3, 10, tzinfo=ZoneInfo("Asia/Macau"))
    status = offpeak_window_status(now)

    assert status["in_offpeak_window"] is True
    assert status["can_collect_freeflow_samples"] is True
    assert status["minutes_until_next_window"] == 0


def test_human_calibration_marks_map_work_as_human_required() -> None:
    now = datetime(2026, 8, 28, 22, 54, tzinfo=ZoneInfo("Asia/Macau"))
    payload = build_human_calibration(
        camera_count=111,
        missing_coordinates=105,
        missing_rois=106,
        missing_flow_lines=109,
        disabled_corridor_names=["Guia Tunnel", "Sai Van Bridge"],
        enabled_corridor_count=3,
        calibration_summary={"configured": 0, "ready": 0, "missing": 111},
        now=now,
    )

    assert payload["human_required"] is True
    assert payload["human_remaining"] == 105 + 106 + 109 + 2
    assert payload["offpeak_window"]["in_offpeak_window"] is False
    tasks = {task["id"]: task for task in payload["tasks"]}
    assert tasks["place-cameras"]["owner"] == "human"
    assert tasks["place-cameras"]["status"] == "blocked"
    assert tasks["place-cameras"]["remaining"] == 105
    assert tasks["collect-offpeak-motion"]["owner"] == "automated"
    assert tasks["collect-offpeak-motion"]["status"] == "waiting"
    assert tasks["run-calibrate-freeflow"]["status"] == "waiting"
    assert "must not be written as free-flow speeds" in tasks["collect-offpeak-motion"]["detail"]


def test_human_calibration_is_ready_inside_the_collection_window() -> None:
    now = datetime(2026, 8, 29, 2, 15, tzinfo=ZoneInfo("Asia/Macau"))
    payload = build_human_calibration(
        camera_count=2,
        missing_coordinates=0,
        missing_rois=0,
        missing_flow_lines=0,
        disabled_corridor_names=[],
        enabled_corridor_count=1,
        calibration_summary={"configured": 0, "ready": 1, "missing": 2},
        now=now,
        min_history=5,
    )

    assert payload["human_required"] is False
    tasks = {task["id"]: task for task in payload["tasks"]}
    assert tasks["collect-offpeak-motion"]["status"] == "ready"
    assert tasks["run-calibrate-freeflow"]["status"] == "ready"
    assert tasks["place-cameras"]["status"] == "done"
