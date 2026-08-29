# traffic-cam-ai-test

A small Macau traffic camera proof-of-concept that discovers live DSAT feeds, handles DSAT reload/anti-bot pages, and captures frames from HLS streams.

## Current repository state

This repo now contains:

- `macau_dsat_feed.py` — compatibility wrapper CLI for the current package.
- `src/trafficcam` — the new package with ingestion, capture, analysis, storage, API, and web scaffolding.
- `tools/` — utility scripts for probing the live DSAT site and inspecting pages.
- `tests/` — unit and integration tests for live DSAT parsing, capture, and analysis behavior.

## How the DSAT live feed workflow works

1. The script probes `https://www.dsat.gov.mo/dsat/realtime.aspx`.
2. It discovers camera detail pages from links and embedded URLs.
3. It fetches each camera detail page and looks for live `.m3u8` HLS URLs, `image.aspx` snapshots, or direct image URLs.
4. If a detail page does not immediately contain a stream URL, it checks for DSAT's reload/continue page.
5. It automatically follows the `realtime_reload.aspx` / `realtime_core4.aspx` flow if present, so the script can resolve the actual live stream URL.
6. Captured frame metadata and future analysis output are persisted in `src/trafficcam/storage`.

## Anti-bot / reload handling

DSAT sometimes requires a reload or "continue" step before exposing the real camera stream. This is the anti-bot mechanism you observed:

- the initial camera link may land on `realtime_reload.aspx` instead of the final detail page,
- the page often contains a link or a meta refresh that leads to the real `realtime_core4.aspx` page,
- our code detects this intermediate page and follows the redirect automatically.

That means the script can still get the live feed without manual clicking, while preserving the same detection and capture flow.

## Getting live camera feeds

### Discover feeds and show a manifest

```bash
python macau_dsat_feed.py --manifest --pretty
```

This command discovers DSAT cameras, resolves detail pages, follows reload pages when needed, and prints a manifest of discovered feed URLs.

### Capture frames from discovered feeds

```bash
python macau_dsat_feed.py --capture-frames --output-dir frames --frame-count 3
```

This will:

- discover live feeds,
- resolve stream URLs from DSAT detail pages,
- follow reload/continue logic when the anti-bot page is present,
- use `ffmpeg` to capture frame images into `frames/`.

### Run repeated capture cycles

```bash
python macau_dsat_feed.py --capture-loop --output-dir frames --frame-count 3 --capture-interval 5 --max-cycles 2
```

This runs the discovery and capture flow repeatedly with a delay between cycles.

### Audit missing camera calibration

```bash
python -m trafficcam.cli audit-config --pretty --report-file output/config-audit.json
```

This compares the current manifest against camera coordinates, density thresholds, ROIs, and flow lines, then writes a report with missing counts, missing camera IDs, and a prioritized `next_calibration_queue` for the cameras closest to fully configured.

## Interpreting the traffic map

The dashboard only applies green/yellow/orange/red traffic colours to analyses
captured within the last 20 minutes. Older observations are labelled stale and
shown in grey. Fresh observations without a per-camera free-flow calibration
are labelled provisional; they are useful operational signals, but they are
not routing-grade speed estimates.

Approximate camera locations are hidden from the map by default to keep the
verified corridor view readable. Enable **Approx markers** to inspect all
discovered cameras. The sidebar continues to list every camera and exposes
whether its location and traffic observation need attention.

Human calibration is still required before the map can look like Google Maps
live traffic:

1. **Place cameras (human).** Drag markers in **Edit positions**, or edit
   `config/camera_coordinates.json`. A first geocoding pass added exact named
   locations for cameras 60 and 62; 103 of 111 cameras are still approximate.
2. **Draw ROIs and flow lines (human).** Edit `config/camera_rois.json` and
   `config/camera_flow_lines.json` against a live frame so occupancy and
   direction are measured on the roadway. A first evidence-based pass now
   covers 25 ROIs and 21 unambiguous single-road flow lines from the saved
   2026-08-28 nighttime burst. See `config/camera_geometry_review.json` for
   provenance and deliberately deferred views.
3. **Verify remaining corridors (human).** Guia Tunnel, Sai Van Bridge, Qingmao
   Port, and Avenida do Ouvidor Arriaga stay disabled until geometry is
   confirmed in `config/camera_corridors.json`.
4. **Collect 02:00–05:00 Asia/Macau motion (automated, time-gated).** Evening
   or daytime captures can refresh live occupancy, but they must not be used as
   free-flow speeds. Use at least 5 frames per camera.
5. **Run `calibrate-freeflow` (automated, blocked until step 4).** Preview with
   `--dry-run` first. Do not persist baselines from off-window samples.

If rain is heavy, postpone calibration review. Rain streaks, glare, spray, and
road reflections can reduce detector confidence and distort lane boundaries.
Rain-affected frames may still be shown as provisional live observations, but
should not establish ROIs, flow lines, density thresholds, or free-flow
baselines.

## Utility scripts

The repository includes helper tools for live inspection:

- `tools/probe_live.py` — probe the DSAT index and verify camera entry extraction.
- `tools/inspect_live_page.py` — inspect the raw DSAT index HTML and locate camera URL matches.
- `tools/inspect_detail.py` — inspect a camera detail page and extract stream-like URLs.

These scripts are for exploratory testing and live website debugging, not the core capture pipeline.

## Running tests

From the repo root:

```bash
python -m pytest -q
```

Or inside Docker:

```bash
docker run --rm --entrypoint python macau-feed -m pytest -q
```

In Docker, the suite includes the new trend analysis tests for `TrendAnalyzer`, the rolling-window baseline helpers, JSONL index support, and incident coalescing.

## Docker support

### Build the image

```bash
docker build -t macau-feed .
```

### Run the dashboard/API

```bash
docker run --rm -p 8000:8000 macau-feed
```

The dashboard is then available at `http://localhost:8000`. Live capture does
not autostart in this process, so API requests remain responsive. Startup warms
the latest-camera cache before Uvicorn reports ready; calibration coverage then
refreshes in the background without delaying dashboard requests.

### Run tests in Docker

```bash
docker run --rm --entrypoint python macau-feed -m pytest -q
```

### Docker Compose

```bash
docker compose up --build
```

This starts the dashboard/API only. Live capture is an explicit, separate
service so model inference and capture work cannot block the Uvicorn process:

```bash
docker compose --profile capture up --build
```

That command starts both the dashboard and `live-capture`. To run collection
without the dashboard, target the capture service directly:

```bash
docker compose --profile capture up --build live-capture
```

The capture loop defaults to 30 cameras, five frames per cycle, and a
300-second interval. Five frames are required for motion/speed samples; a
1-frame cycle can only refresh occupancy. Override those values with
`PIPELINE_LIMIT`, `PIPELINE_FRAME_COUNT`, and `PIPELINE_INTERVAL`.

A one-shot collection of the six verified cameras:

```bash
docker compose --profile capture run --no-deps live-capture run-once --frame-count 5 --limit 6 --manifest-file data/manifest.json --output-dir output/live --data-dir data
```

### Notes

- The Docker image includes `ffmpeg`, `pytest`, and `fastapi`.
- The default container entrypoint is `python -m trafficcam.cli`.
- Override the entrypoint to run package tests or one-off Python commands.
- Model downloads are cached under `model-cache/` on the host. YOLO weights are expected at `model-cache/ultralytics/weights/` and the code prefers that cache path before falling back to a repo-local file.

## TODO

- [x] Wire host-mounted model cache paths and prefer cached weights in code for repeated Docker test runs.
- [ ] Validate the YOLO backend in a fresh live end-to-end Docker run and confirm current records are regenerated with the new metadata shape.
- [x] Validate time-spaced burst capture against a live DSAT feed by confirming a 3-frame burst produces more than one distinct file hash.
- [ ] Add camera geolocation data (lat/lon) so cameras can be placed accurately on a dashboard map.
- [x] Build a frontend/dashboard layer that visualizes the latest density by district, sub-district, and camera (`/` serves a dashboard with overview cards, camera list, and Leaflet map; `/api/overview` provides city-wide aggregates).
- [ ] Add camera profile routing so pedestrian-dominant views can be excluded from vehicle traffic analytics.
- [ ] Refine per-camera ROI polygons against real frames (currently conservative full-width polygons).
- [ ] Run `python tools/calibrate_thresholds.py` after accumulating live history to replace global density thresholds with per-camera percentile-based ones.