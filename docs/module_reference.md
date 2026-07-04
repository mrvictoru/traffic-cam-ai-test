# Traffic Cam AI Platform Module Reference

This document describes the key modules in the repository, the files they contain, their primary purpose, and the inputs/outputs for the main functions and classes.

## Overview

The current implementation is organized into the following functional areas:

- `cli` — command-line entry point.
- `ingestion` — DSAT camera discovery and manifest building.
- `capture` — frame capture orchestration and ffmpeg execution.
- `analysis` — traffic analysis, trend detection, incident detection, and event coalescing.
- `storage` — abstract storage interface, JSON file backend, and per-camera index support.
- `api` — FastAPI scaffold for future REST endpoints.
- `web` — dashboard scaffold.
- `tools` — utility scripts for auxiliary operations.

---

## `src/trafficcam/cli.py`

### Purpose

Provide the package CLI entry point.

### Main components

- `build_parser() -> argparse.ArgumentParser`
  - Configures CLI options:
    - `--mode` — one of `discover`, `capture`, or `analyze`.
    - `--output-dir` — directory for generated output.

- `main() -> int`
  - Parses command-line arguments and prints the selected mode and output directory.

### Usage

Run the CLI directly:

```bash
python -m trafficcam.cli --mode discover --output-dir output
```

This is currently a scaffold and does not yet execute the full pipeline.

---

## `src/trafficcam/ingestion/dsat_client.py`

### Purpose

Discover DSLR camera feeds from DSAT and resolve detail pages into stream URLs.

### Key classes and functions

- `DSATClient`
  - Constructor: `DSATClient(index_url: str | None = None, fetcher: Callable[[str], str] | None = None)`
  - `discover_cameras(limit: int | None = None) -> list[CameraFeed]`
    - Returns a list of `CameraFeed` objects discovered from DSAT.
    - Uses `build_manifest()` and converts its camera payloads into `CameraFeed`.
  - `build_manifest(limit: int | None = None) -> dict`
    - Fetches the DSAT index page and extracts camera detail URLs.
    - Fetches each camera detail page and extracts stream URLs.
    - If a page is a reload/continue page, follows the redirect and re-extracts stream URLs.
    - Returns a manifest containing:
      - `source_url`
      - `fetched_at`
      - `camera_count`
      - `cameras`: list of payloads with `cam_id`, `name`, `detail_url`, `stream_urls`, and optional `fetch_error`.
  - `normalize_detail_url(detail_url: str) -> str`
    - Normalizes a detail page URL to a canonical string representation.

- `CameraEntry`
  - Internal helper representing a discovered camera before manifest construction.

- `extract_camera_entries(html: str, base_url: str) -> list[CameraEntry]`
  - Parses an index page and extracts camera detail page links.

- `extract_stream_urls(html: str, base_url: str) -> list[str]`
  - Parses a detail page and extracts candidate stream URLs:
    - `.m3u8` HLS URLs
    - `image.aspx` snapshot URLs
    - direct image file URLs

- `_follow_reload_page(html: str, base_url: str) -> str | None`
  - Detects DSAT reload or meta-refresh pages and returns the redirect URL.

### Inputs and outputs

- Input: DSAT index URL and HTML content.
- Output: structured manifest and resolved stream URLs.

### Usage

```python
from trafficcam.ingestion.dsat_client import DSATClient

client = DSATClient()
manifest = client.build_manifest(limit=10)
```

---

## `src/trafficcam/capture/ffmpeg_runner.py`

### Purpose

Run `ffmpeg` to capture frames from a stream URL.

### Key class and method

- `FFmpegRunner`
  - Constructor: `FFmpegRunner(ffmpeg_path: str = "ffmpeg")`
  - `capture_frame(stream_url: str, output_path: str | Path) -> None`
    - Ensures the parent output directory exists.
    - Runs `ffmpeg -y -i <stream_url> -frames:v 1 <output_path>`.
    - Returns no payload; use the filesystem output path for the captured frame.

### Usage

```python
from trafficcam.capture.ffmpeg_runner import FFmpegRunner

runner = FFmpegRunner()
runner.capture_frame("https://example.com/stream.m3u8", "output/frame.jpg")
```

---

## `src/trafficcam/capture/frame_capturer.py`

### Purpose

Orchestrate capture jobs for discovered cameras and feeds.

### Key class and methods

- `FrameCapturer`
  - Constructor: `FrameCapturer(output_dir: str | Path | None = None, ffmpeg_runner: FFmpegRunner | None = None)`
    - Creates and owns an output directory.
    - Uses `FFmpegRunner` for actual frame capture.

- `capture(cameras: Iterable[CameraFeed], frame_count: int = 1) -> list[CaptureResult]`
  - Placeholder implementation that writes stub bytes.
  - Returns `CaptureResult` objects containing `camera_id`, `output_path`, `success`, and `notes`.

- `capture_frames_from_manifest(manifest: dict, frame_count: int = 3, ffmpeg_path: list[str] | None = None) -> list[dict]`
  - Extracts cameras from the manifest.
  - Selects the first `.m3u8` stream URL per camera.
  - Runs `ffmpeg` and writes frames into a camera-specific output subdirectory.
  - Returns a list of result dictionaries containing:
    - `cam_id`
    - `stream_url`
    - `returncode`
    - `frame_paths`
    - `stdout`
    - `stderr`

- `capture_frames_loop(index_url: str, output_root: str | Path | None = None, frame_count: int = 3, interval_seconds: float = 5.0, max_cycles: int | None = None, ffmpeg_path: list[str] | None = None) -> list[dict]`
  - Repeatedly fetches a DSAT manifest, captures frames, and sleeps between cycles.
  - Useful for continuous capture scenarios.

### Usage

```python
from trafficcam.capture.frame_capturer import FrameCapturer

capturer = FrameCapturer(output_dir="frames")
results = capturer.capture_frames_loop("https://www.dsat.gov.mo/dsat/realtime.aspx", max_cycles=2)
```

---

## `src/trafficcam/analysis/traffic_detector.py`

### Purpose

Scaffold for future traffic density analysis of individual images.

### Key class and method

- `TrafficDetector`
  - `analyze(image_path: str) -> dict`
    - Returns a placeholder dictionary with `image_path`, `label`, and `confidence`.

### Usage

```python
from trafficcam.analysis.traffic_detector import TrafficDetector

analyzer = TrafficDetector()
result = analyzer.analyze("frame.jpg")
```

---

## `src/trafficcam/analysis/scene_classifier.py`

### Purpose

Scaffold for future scene classification of images.

### Key class and method

- `SceneClassifier`
  - `classify(image_path: str) -> dict`
    - Returns a placeholder dictionary with `image_path` and `scene`.

### Usage

```python
from trafficcam.analysis.scene_classifier import SceneClassifier

classifier = SceneClassifier()
scene = classifier.classify("frame.jpg")
```

---

## `src/trafficcam/analysis/baseline.py`

### Purpose

Build baselines for trend anomaly detection using historical records.

### Functions

- `hour_of(record: dict) -> int`
  - Input: persisted record with `captured_at` timestamp.
  - Output: UTC hour of the record.

- `baseline_values(records: Sequence[dict], target_idx: int, *, window_records: int, hour_buckets: int, series_extractor: Callable[[dict], float | int]) -> list[float]`
  - Input: record list, current index, window size, hour bucket count, extractor function.
  - Output: prior numeric values used as the anomaly baseline.
  - Behavior:
    - If `hour_buckets > 1`, retains only prior records whose hour-of-day matches the current record.
    - If `window_records > 0`, returns at most the most recent window of prior values.

- `zscore_with_window(value: float, baseline: Sequence[float], *, severity_cap: float = 10.0) -> float`
  - Input: current numeric value and baseline values.
  - Output: signed z-score.
  - Behavior:
    - Returns `0.0` when baseline has fewer than 2 values.
    - Caps zero-variance deviations to `±severity_cap` instead of `±inf`.

### Usage

This module is used by the trend detection logic in `analysis/trends.py`.

---

## `src/trafficcam/analysis/coalesce.py`

### Purpose

Group sustained incidents into a single representative alert.

### Function

- `coalesce_incidents(incidents: Sequence[IncidentEvent], *, cooldown_minutes: float = 10.0) -> list[CoalescedIncident]`
  - Input: list of `IncidentEvent` objects.
  - Output: list of `CoalescedIncident` objects.
  - Behavior:
    - Sorts incidents by timestamp.
    - Merges same-camera events of the same type when they occur within `cooldown_minutes` of the previous incident in the group.
    - Tracks `coalesced_count`, `coalesced_timestamps`, and the highest `severity`.

### Usage

This is used by `TrendAnalyzer.detect_incidents(..., coalesce=True)`.

---

## `src/trafficcam/analysis/trends.py`

### Purpose

Detect traffic trends and anomalous incidents from persisted analysis history.

### Key classes and functions

- `compute_directional_flow_split(tracks: Iterable[Track], line: tuple[Point, Point]) -> FlowSplit`
  - Input:
    - `tracks`: iterable of trajectories; each trajectory is a list of `(track_id, frame_idx, (cx, cy))` points.
    - `line`: counting line specified by two points.
  - Output: `FlowSplit` object with `northbound`, `southbound`, and `total` counts.
  - Behavior:
    - Detects line crossings and assigns direction based on signed distance.

- `detect_congestion_events(records: Sequence[dict], camera_id: str, density_levels: set[str]) -> list[CongestionEvent]`
  - Input: ordered records for one camera and a set like `{"heavy", "blocked"}`.
  - Output: contiguous congestion runs, each with `start`, `end`, `duration`, and `record_count`.

- `detect_incidents(records: Sequence[dict], camera_id: str, z_threshold: float = 2.0, min_history: int = 5, window_records: int = 288, hour_buckets: int = 24, severity_cap: float = 10.0) -> list[IncidentEvent]`
  - Input: ordered camera records and anomaly detection parameters.
  - Output: list of `IncidentEvent` objects.
  - Behavior:
    - Computes flow and density baselines using `analysis/baseline.py`.
    - Flags flows far below baseline as `flow_drop`.
    - Flags density ordinals far above baseline as `density_spike`.

- `TrendAnalyzer`
  - Constructor: `TrendAnalyzer(store: StorageBackend, *, window_records: int = 288, hour_buckets: int = 24, cooldown_minutes: float = 10.0)`
  - `load_records(camera_id: str) -> list[dict]`
    - Loads persisted records from `analyses/{camera_id}/index.jsonl` when available.
    - Falls back to scanning `analyses/{camera_id}/*.json`.
  - `detect_congestion_events(camera_id: str, density_levels: set[str] = frozenset({"heavy", "blocked"})) -> list[CongestionEvent]`
  - `detect_incidents(camera_id: str, z_threshold: float = 2.0, min_history: int = 5, persist: bool = False, window_records: int | None = None, hour_buckets: int | None = None, coalesce: bool = False, cooldown_minutes: float | None = None) -> list[IncidentEvent]`
    - Optionally persists incidents under `incidents/{camera_id}/{timestamp}.json` when `persist=True`.
    - Optionally coalesces incidents when `coalesce=True`.

### Usage

```python
from trafficcam.storage.json_store import JsonStore
from trafficcam.analysis.trends import TrendAnalyzer

store = JsonStore("data")
trend = TrendAnalyzer(store)
incidents = trend.detect_incidents("cam1", persist=True, coalesce=True)
```

---

## `src/trafficcam/storage/base.py`

### Purpose

Abstract interface for storage backends.

### Methods

- `save_json(path: str | Path, payload: Any) -> None`
- `load_json(path: str | Path) -> Any`
- `append_jsonl(path: str | Path, payload: Any) -> None`
- `load_jsonl(path: str | Path) -> list[Any]`
- `save_jsonl(path: str | Path, payloads: list[Any]) -> None`
- `list_records(prefix: str = "") -> Iterable[str]`

### Usage

`JsonStore` implements this interface and is the current backend.

---

## `src/trafficcam/storage/json_store.py`

### Purpose

File-based JSON storage for pipeline artifacts.

### Behavior

- Saves plain JSON files under a local data root (`data/` by default).
- Reads JSON files back into Python objects.
- Appends and loads newline-delimited JSON lists (JSONL).
- Lists record file paths with prefix-based filtering.

### Important details

- `list_records(prefix)` now matches prefixes exactly rather than substring matching.
- JSONL support is used for per-camera indexes.

### Usage

```python
from trafficcam.storage.json_store import JsonStore

store = JsonStore("data")
store.save_json("analyses/cam1/001.json", record)
items = store.list_records(prefix="analyses/cam1/")
```

---

## `src/trafficcam/storage/index.py`

### Purpose

Maintain a compact JSONL index per camera for faster record loading.

### Key functions

- `build_index_entry(record: dict, record_path: str) -> AnalysisIndexEntry`
  - Converts a full analysis record to a compact index entry.

- `append_to_index(store: StorageBackend, camera_id: str, record: dict, record_path: str) -> None`
  - Appends one index line to `analyses/{camera_id}/index.jsonl`.

- `rebuild_camera_index(store: StorageBackend, camera_id: str) -> None`
  - Rebuilds the entire index for a camera by scanning all persisted JSON records.

### Usage

```python
from trafficcam.storage.index import append_to_index, rebuild_camera_index
from trafficcam.storage.json_store import JsonStore

store = JsonStore("data")
append_to_index(store, "cam1", record, "analyses/cam1/001.json")
rebuild_camera_index(store, "cam1")
```

---

## `src/trafficcam/storage/database.py`

### Purpose

Placeholder for a future database-backed storage backend.

### Behavior

- `DatabaseStore(connection_string: str | None = None)`
  - Stores the connection string for later use.

---

## `src/trafficcam/api/main.py`

### Purpose

FastAPI application scaffold.

### Key object

- `app: FastAPI`
  - Provides a `/health` endpoint that returns `{"status": "ok"}`.

### Usage

This module can be used as the app instance for API server startup.

---

## `src/trafficcam/api/routes.py`

### Purpose

API route scaffold.

### Key object

- `router: APIRouter`
  - Currently defines `/cameras`, returning an empty list.

---

## `src/trafficcam/web/app.py`

### Purpose

Web dashboard scaffold.

### Key function

- `render_dashboard() -> str`
  - Returns placeholder HTML.

---

## `tools/rebuild_indices.py`

### Purpose

Utility to rebuild per-camera analysis indexes from stored records.

### Behavior

- Instantiates `JsonStore()` with default `data/` root.
- Iterates through `data/analyses/*` directories.
- Calls `rebuild_camera_index()` for each camera.

### Usage

```bash
python tools/rebuild_indices.py
```

---

## Notes on current implementation state

- `traffic_detector.py` and `scene_classifier.py` are placeholders for future CV-based analysis.
- `metrics.py` provides a simple average confidence helper.
- `database.py` is a future storage backend stub.
- The current live pipeline is primarily file-based and scaffolded around DSAT discovery, frame capture, and trend analysis.
