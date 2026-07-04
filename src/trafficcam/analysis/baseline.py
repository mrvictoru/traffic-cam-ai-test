"""Baseline helpers for rolling-window and hour-bucketed incident detection."""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Callable, Sequence


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).replace(tzinfo=None)


def hour_of(record: dict) -> int:
    """Return the UTC hour bucket for a persisted analysis record."""
    return _parse_timestamp(record["captured_at"]).hour


def baseline_values(
    records: Sequence[dict],
    target_idx: int,
    *,
    window_records: int,
    hour_buckets: int,
    series_extractor: Callable[[dict], float | int],
) -> list[float]:
    """Return prior-series values used as the anomaly baseline.

    When `hour_buckets` is greater than 1, the baseline is restricted to prior
    records whose hour-of-day matches the target record. `window_records <= 0`
    means "whole available history" after any hour filtering.
    """
    prior_records = list(records[:target_idx])
    if hour_buckets > 1 and target_idx < len(records):
        target_hour = hour_of(records[target_idx])
        prior_records = [record for record in prior_records if hour_of(record) == target_hour]
    if window_records > 0:
        prior_records = prior_records[-window_records:]
    return [float(series_extractor(record)) for record in prior_records]


def zscore_with_window(
    value: float,
    baseline: Sequence[float],
    *,
    severity_cap: float = 10.0,
) -> float:
    """Compute a signed z-score against a bounded baseline.

    Returns 0 when there is not enough baseline history. When the baseline has
    zero variance, any non-zero deviation is capped to `severity_cap` while
    preserving sign.
    """
    if len(baseline) < 2:
        return 0.0
    mean = statistics.fmean(baseline)
    try:
        stdev = statistics.stdev(baseline)
    except statistics.StatisticsError:
        stdev = 0.0
    if stdev == 0:
        if value < mean:
            return -severity_cap
        if value > mean:
            return severity_cap
        return 0.0
    return (value - mean) / stdev
