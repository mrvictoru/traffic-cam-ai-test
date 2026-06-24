"""Post-hoc temporal trend analysis over persisted analysis records.

This module is the implementation of *Option B* from the Phase 4 plan:
- directional flow split (per-burst, pure function over tracks),
- congestion duration detection (run-length encoding on density history),
- incident detection (z-score based anomaly detection vs a rolling baseline).

It operates on records persisted via the `JsonStore` under
`analyses/{camera_id}/*.json` and (optionally) writes detected incidents back
to `incidents/{camera_id}/{ts}.json`.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from .baseline import baseline_values, zscore_with_window
from .coalesce import coalesce_incidents
from ..models import (
    CoalescedIncident,
    CongestionEvent,
    FlowSplit,
    IncidentEvent,
)
from ..storage.base import StorageBackend


LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Directional flow split (pure function over per-frame tracks)
# ---------------------------------------------------------------------------


Point = tuple[float, float]
Track = list[tuple[int, int, Point]]  # [(track_id, frame_idx, (cx, cy)), ...]


def _signed_side(p: Point, line: tuple[Point, Point]) -> float:
    """Return the signed perpendicular distance of `p` from the line.

    Positive = one side, negative = the other. Zero = on the line.
    The sign convention follows image coordinates: y increases downward,
    so a point above the line has negative signed distance.
    """
    (x1, y1), (x2, y2) = line
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return 0.0
    return ((p[0] - x1) * dy - (p[1] - y1) * dx) / math.sqrt(length_sq)


def _crosses_line(
    p_prev: Point, p_curr: Point, line: tuple[Point, Point]
) -> bool:
    """True if the segment p_prev->p_curr intersects the counting line."""
    s_prev = _signed_side(p_prev, line)
    s_curr = _signed_side(p_curr, line)
    # Strict crossing: signs differ (ignoring exact-on-line edge cases).
    return s_prev * s_curr < 0


def compute_directional_flow_split(
    tracks: Iterable[Track],
    line: tuple[Point, Point],
) -> FlowSplit:
    """Count unique track IDs that cross `line` in each direction.

    A track is counted at most once per direction across its lifetime so
    wiggling across the line multiple times doesn't inflate the count.

    `tracks` is an iterable of trajectories; each trajectory is a list of
    `(track_id, frame_idx, (cx, cy))` points in chronological order.
    Coordinates are expected to be in image space (y grows downward).
    """
    nb_ids: set[int] = set()
    sb_ids: set[int] = set()
    for track in tracks:
        if len(track) < 2:
            continue
        # Convention: "northbound" = the centroid moves from below the line
        # to above it (i.e. the signed-side value goes from negative to
        # positive). This is the opposite of y-decreasing-in-image-coords;
        # here we treat "above the line in image space" as the northbound
        # direction.
        for i in range(1, len(track)):
            _, _, p_prev = track[i - 1]
            track_id, _, p_curr = track[i]
            if not _crosses_line(p_prev, p_curr, line):
                continue
            s_prev = _signed_side(p_prev, line)
            s_curr = _signed_side(p_curr, line)
            if s_prev < 0 and s_curr > 0:
                nb_ids.add(track_id)
            elif s_prev > 0 and s_curr < 0:
                sb_ids.add(track_id)
    return FlowSplit(northbound=len(nb_ids), southbound=len(sb_ids))


# ---------------------------------------------------------------------------
# Record loading helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating a trailing 'Z'."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _load_records(store: StorageBackend, camera_id: str) -> list[dict]:
    """Load and parse all analysis records for a camera, sorted by time."""
    prefix = f"analyses/{camera_id}/"
    index_path = f"analyses/{camera_id}/index.jsonl"
    try:
        index_entries = store.load_jsonl(index_path)
    except FileNotFoundError:
        index_entries = None

    if index_entries is not None:
        records = []
        for entry in index_entries:
            density = str(entry.get("density", "unknown"))
            flow_total = int(entry.get("flow_total", 0))
            flow_nb = int(entry.get("flow_nb", 0))
            flow_sb = int(entry.get("flow_sb", 0))
            records.append(
                {
                    "camera_id": camera_id,
                    "captured_at": entry["captured_at"],
                    "label": density,
                    "details": {
                        "density": density,
                        "flow_rate_vph": {
                            "northbound": flow_nb,
                            "southbound": flow_sb,
                            "total": flow_total,
                        },
                    },
                    "_path": entry.get("record_path", ""),
                }
            )
        records.sort(key=lambda record: record["captured_at"])
        return records

    LOGGER.warning("Falling back to full scan for %s because %s is missing", camera_id, index_path)
    records: list[dict] = []
    for path in store.list_records(prefix=prefix):
        if path.endswith("index.jsonl"):
            continue
        payload = store.load_json(path)
        if not isinstance(payload, dict):
            continue
        if "captured_at" not in payload:
            continue
        payload["_path"] = path
        records.append(payload)
    records.sort(key=lambda r: r["captured_at"])
    return records


def _density_from_record(record: dict) -> str | None:
    """Extract the density bucket from a record's details or top-level label."""
    details = record.get("details") or {}
    if "density" in details:
        return str(details["density"])
    return record.get("label")


def _flow_total_from_record(record: dict) -> int:
    """Extract total flow rate from a record (legacy scalar or new dict)."""
    details = record.get("details") or {}
    raw = details.get("flow_rate_vph", 0)
    if isinstance(raw, dict):
        return int(raw.get("total", 0))
    return int(raw)


# ---------------------------------------------------------------------------
# Congestion duration detection
# ---------------------------------------------------------------------------


def _consecutive_runs(
    records: Sequence[dict],
    predicate,
) -> Iterable[list[dict]]:
    """Yield runs of consecutive records where `predicate(record)` is True."""
    run: list[dict] = []
    for rec in records:
        if predicate(rec):
            run.append(rec)
        else:
            if run:
                yield run
                run = []
    if run:
        yield run


def detect_congestion_events(
    records: Sequence[dict],
    camera_id: str,
    density_levels: set[str],
) -> list[CongestionEvent]:
    """Detect contiguous runs of congestion-level density for one camera.

    A `CongestionEvent` is emitted for every maximal contiguous run of
    records whose density is in `density_levels`. Runs are separated by at
    least one record whose density is not in the set.
    """
    events: list[CongestionEvent] = []
    levels = {lvl.lower() for lvl in density_levels}
    for run in _consecutive_runs(
        records, lambda r: (_density_from_record(r) or "").lower() in levels
    ):
        first, last = run[0], run[-1]
        start = _parse_timestamp(first["captured_at"])
        end = _parse_timestamp(last["captured_at"])
        events.append(
            CongestionEvent(
                camera_id=camera_id,
                density=str(_density_from_record(first) or "unknown"),
                start=start,
                end=end,
                duration=end - start,
                record_count=len(run),
                details={
                    "timestamps": [r["captured_at"] for r in run],
                },
            )
        )
    return events


# ---------------------------------------------------------------------------
# Incident detection (z-score vs rolling baseline)
# ---------------------------------------------------------------------------


# Ordinal encoding of density levels for z-score computation.
# Higher = more congested.
_DENSITY_ORDINAL = {
    "light": 0,
    "moderate": 1,
    "heavy": 2,
    "blocked": 3,
}


def detect_incidents(
    records: Sequence[dict],
    camera_id: str,
    z_threshold: float = 2.0,
    min_history: int = 5,
    window_records: int = 288,
    hour_buckets: int = 24,
    severity_cap: float = 10.0,
) -> list[IncidentEvent]:
    """Detect anomalous records using a z-score against prior history.

    For each record after the first `min_history` records, the record's
    `flow_rate_vph.total` and density ordinal are compared against the
    baseline of preceding records. A record is flagged when:

    - flow_total is `z_threshold` stdevs *below* the baseline (`flow_drop`),
      or
    - density ordinal is `z_threshold` stdevs *above* the baseline
      (`density_spike`).

    Returns the list of detected incidents in chronological order.
    """
    if len(records) < min_history + 1:
        return []

    incidents: list[IncidentEvent] = []

    # Pre-extract numeric series for efficient z-score computation.
    flow_series = [_flow_total_from_record(r) for r in records]
    density_series = [
        _DENSITY_ORDINAL.get((_density_from_record(r) or "").lower(), 0)
        for r in records
    ]

    for i in range(min_history, len(records)):
        rec = records[i]
        ts = _parse_timestamp(rec["captured_at"])

        # Build baselines from records strictly before i.
        flow_baseline = baseline_values(
            records,
            i,
            window_records=window_records,
            hour_buckets=hour_buckets,
            series_extractor=_flow_total_from_record,
        )
        density_baseline = baseline_values(
            records,
            i,
            window_records=window_records,
            hour_buckets=hour_buckets,
            series_extractor=lambda record: _DENSITY_ORDINAL.get(
                (_density_from_record(record) or "").lower(),
                0,
            ),
        )

        # Flow drop: sharply lower than baseline.
        z_flow = zscore_with_window(
            flow_series[i],
            flow_baseline,
            severity_cap=severity_cap,
        )
        if z_flow <= -z_threshold:
            incidents.append(
                IncidentEvent(
                    camera_id=camera_id,
                    incident_type="flow_drop",
                    timestamp=ts,
                    severity=abs(z_flow),
                    details={
                        "flow_total": flow_series[i],
                        "baseline_mean": statistics.fmean(flow_baseline),
                        "baseline_stdev": statistics.stdev(flow_baseline)
                        if len(flow_baseline) > 1
                        else 0.0,
                        "z_score": z_flow,
                        "record_path": rec.get("_path", ""),
                    },
                )
            )

        # Density spike: sharply higher than baseline.
        z_density = zscore_with_window(
            density_series[i],
            density_baseline,
            severity_cap=severity_cap,
        )
        if z_density >= z_threshold:
            incidents.append(
                IncidentEvent(
                    camera_id=camera_id,
                    incident_type="density_spike",
                    timestamp=ts,
                    severity=z_density,
                    details={
                        "density": _density_from_record(rec),
                        "baseline_mean": statistics.fmean(density_baseline),
                        "baseline_stdev": statistics.stdev(density_baseline)
                        if len(density_baseline) > 1
                        else 0.0,
                        "z_score": z_density,
                    },
                )
            )

    return incidents


# ---------------------------------------------------------------------------
# Public façade: TrendAnalyzer
# ---------------------------------------------------------------------------


class TrendAnalyzer:
    """High-level temporal analysis over a camera's persisted records."""

    def __init__(
        self,
        store: StorageBackend,
        *,
        window_records: int = 288,
        hour_buckets: int = 24,
        cooldown_minutes: float = 10.0,
    ) -> None:
        self.store = store
        self.window_records = window_records
        self.hour_buckets = hour_buckets
        self.cooldown_minutes = cooldown_minutes

    # -- query helpers --

    def load_records(self, camera_id: str) -> list[dict]:
        """Load and chronologically sort the camera's analysis records."""
        return _load_records(self.store, camera_id)

    # -- congestion duration --

    def detect_congestion_events(
        self,
        camera_id: str,
        density_levels: set[str] = frozenset({"heavy", "blocked"}),
    ) -> list[CongestionEvent]:
        records = self.load_records(camera_id)
        return detect_congestion_events(records, camera_id, set(density_levels))

    # -- incident detection --

    def detect_incidents(
        self,
        camera_id: str,
        z_threshold: float = 2.0,
        min_history: int = 5,
        persist: bool = False,
        window_records: int | None = None,
        hour_buckets: int | None = None,
        coalesce: bool = False,
        cooldown_minutes: float | None = None,
    ) -> list[IncidentEvent]:
        records = self.load_records(camera_id)
        incidents = detect_incidents(
            records,
            camera_id,
            z_threshold=z_threshold,
            min_history=min_history,
            window_records=self.window_records if window_records is None else window_records,
            hour_buckets=self.hour_buckets if hour_buckets is None else hour_buckets,
        )
        if coalesce:
            incidents = coalesce_incidents(
                incidents,
                cooldown_minutes=self.cooldown_minutes if cooldown_minutes is None else cooldown_minutes,
            )
        if persist:
            for ev in incidents:
                self._persist_incident(ev)
        return incidents

    # -- persistence --

    def _persist_incident(self, event: IncidentEvent) -> Path:
        """Persist a single incident event under incidents/{cam_id}/{ts}.json."""
        ts_key = event.timestamp.strftime("%Y%m%dT%H%M%SZ")
        path = f"incidents/{event.camera_id}/{ts_key}_{event.incident_type}.json"
        payload = asdict(event)
        # datetime / timedelta are not JSON-serializable as-is.
        payload["timestamp"] = event.timestamp.isoformat() + "Z"
        self.store.save_json(path, payload)
        return path
