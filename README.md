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

### Run the pipeline

```bash
docker run macau-feed
```

### Run tests in Docker

```bash
docker run --rm --entrypoint python macau-feed -m pytest -q
```

### Docker Compose

```bash
docker-compose up --build
```

If you want to pass custom arguments, edit the `docker-compose.yml` service command or override the entrypoint as needed.

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
- [ ] Build a frontend/dashboard layer that visualizes the latest density by district, sub-district, and camera.
- [ ] Add camera profile routing so pedestrian-dominant views can be excluded from vehicle traffic analytics.