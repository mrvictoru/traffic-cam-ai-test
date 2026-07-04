"""Tests for rolling-window and hour-bucketed incident baselines."""

from __future__ import annotations

from datetime import datetime, timedelta

from trafficcam.analysis.baseline import baseline_values, hour_of, zscore_with_window


def _record(ts: datetime, flow_total: int, density: str = "moderate") -> dict:
    return {
        "captured_at": ts.isoformat() + "Z",
        "label": density,
        "details": {
            "density": density,
            "flow_rate_vph": {"northbound": 0, "southbound": 0, "total": flow_total},
        },
    }


def test_hour_of_reads_utc_hour():
    record = _record(datetime(2026, 6, 24, 3, 15, 0), 10)
    assert hour_of(record) == 3


def test_baseline_values_uses_rolling_window_without_hour_buckets():
    base = datetime(2026, 6, 24, 8, 0, 0)
    records = [_record(base + timedelta(minutes=5 * i), flow_total=i) for i in range(10)]

    values = baseline_values(
        records,
        9,
        window_records=3,
        hour_buckets=1,
        series_extractor=lambda rec: rec["details"]["flow_rate_vph"]["total"],
    )

    assert values == [6, 7, 8]


def test_baseline_values_filters_to_same_hour_bucket():
    records = [
        _record(datetime(2026, 6, 24, 8, 0, 0), 100),
        _record(datetime(2026, 6, 24, 9, 0, 0), 200),
        _record(datetime(2026, 6, 25, 8, 0, 0), 110),
        _record(datetime(2026, 6, 25, 9, 0, 0), 210),
        _record(datetime(2026, 6, 26, 8, 0, 0), 120),
    ]

    values = baseline_values(
        records,
        4,
        window_records=10,
        hour_buckets=24,
        series_extractor=lambda rec: rec["details"]["flow_rate_vph"]["total"],
    )

    assert values == [100, 110]


def test_baseline_values_caps_same_hour_history_by_window_size():
    records = [
        _record(datetime(2026, 6, 20 + i, 8, 0, 0), 100 + i * 10)
        for i in range(5)
    ]

    values = baseline_values(
        records,
        4,
        window_records=2,
        hour_buckets=24,
        series_extractor=lambda rec: rec["details"]["flow_rate_vph"]["total"],
    )

    assert values == [120, 130]


def test_zscore_with_window_caps_infinite_spike():
    assert zscore_with_window(20, [10, 10, 10], severity_cap=7.5) == 7.5
    assert zscore_with_window(0, [10, 10, 10], severity_cap=7.5) == -7.5
