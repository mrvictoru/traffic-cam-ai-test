# Macau Traffic Cam AI Platform Implementation Plan

## 1. Purpose

This repository should evolve from a simple DSAT feed probe into a small but extensible traffic intelligence platform. The end goal is to:

1. discover Macau traffic camera feeds from DSAT,
2. capture frames reliably from live streams,
3. run lightweight traffic analysis on those frames,
4. persist results for later review,
5. expose the data through a simple API and optional web UI.

The current prototype in [macau_dsat_feed.py](../macau_dsat_feed.py) is the foundation. The next step is to turn it into a modular system with explicit responsibilities.

---

## 2. Target architecture

The platform should be split into clear modules:

- Ingestion: discover camera feeds from DSAT and build a structured manifest.
- Capture: download or extract frames from the discovered live feeds.
- Analysis: infer traffic state, congestion, and scene context from frames.
- Storage: save manifests, frame metadata, analysis results, and health states.
- API: expose the data via a small REST API.
- Web UI: provide a simple dashboard for browsing cameras and results.
- Ops: handle configuration, scheduling, and containerized execution.

---

## 3. Proposed repository layout

```text
traffic-cam-ai-test/
├── docs/
│   └── implementation-plan.md
├── src/
│   └── trafficcam/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── dsat_client.py
│       │   ├── manifest_builder.py
│       │   └── schemas.py
│       ├── capture/
│       │   ├── __init__.py
│       │   ├── frame_capturer.py
│       │   ├── ffmpeg_runner.py
│       │   └── retry_policy.py
│       ├── analysis/
│       │   ├── __init__.py
│       │   ├── traffic_detector.py
│       │   ├── scene_classifier.py
│       │   ├── baseline.py
│       │   ├── coalesce.py
│       │   ├── trends.py
│       │   └── metrics.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── json_store.py
│       │   ├── index.py
│       │   └── database.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   └── routes.py
│       └── web/
│           ├── __init__.py
│           └── app.py
├── tests/
│   ├── fixtures/
│   │   ├── dsat_index.html
│   │   └── dsat_detail.html
│   ├── unit/
│   │   ├── test_dsat_client.py
│   │   ├── test_manifest_builder.py
│   │   ├── test_frame_capturer.py
│   │   └── test_analysis.py
│   └── integration/
│       ├── test_live_capture.py
│       └── test_api.py
├── scripts/
│   └── run_pipeline.sh
├── Dockerfile
├── docker-compose.yml
├── macau_dsat_feed.py
└── README.md
```

---

## 4. Implementation phases

### Phase 1 — Foundation and packaging

Goal: make the current prototype easier to evolve.

Tasks:
- keep [macau_dsat_feed.py](../macau_dsat_feed.py) as a compatibility wrapper for the new package,
- introduce a package under [src/trafficcam](../src/trafficcam),
- centralize configuration values and environment settings,
- define shared data models for cameras, feeds, captures, and analysis results.

### Phase 2 — DSAT ingestion

Goal: make feed discovery robust and reusable.

Tasks:
- support discovery from the DSAT index and detail pages,
- gracefully handle anti-bot/reload flows,
- normalize discovered URLs into a structured manifest,
- save and re-use the manifest between runs.

### Phase 3 — Frame capture

Goal: reliably capture frames from the discovered streams.

Tasks:
- wrap the current ffmpeg-based capture flow in a dedicated module,
- support single-shot capture and repeated capture loops,
- store frame files in a stable directory structure,
- record capture metadata such as timestamp, source, and success state.

### Phase 4 — Analysis

Goal: extract useful traffic insights from the captured images.

Tasks:
- classify traffic density at a high level,
- optionally detect weather or lighting conditions,
- produce structured analysis records,
- keep the analysis logic modular so the model can be upgraded later,
- add post-hoc trend analysis over persisted records,
- detect incidents from flow drops and density spikes using rolling baselines,
- coalesce sustained incidents into representative alerts.

### Phase 4A — Traffic layer quality improvements (Google Maps-style traffic grading)

Goal: move from a vehicle-count approximation to a road-speed-based traffic estimate that more closely matches the semantics of a live traffic layer.

The current prototype already captures the right raw ingredients: object detections, tracked motion, flow splits, confidence, and scene context. The next improvement is to convert those signals into a more accurate estimate of network speed and congestion instead of using only occupancy.

#### 4A.1 Speed-based congestion scoring

The primary improvement is to treat speed as the main signal and use occupancy only as a second signal.

- The tracker already records centroid trajectories across a burst of frames.
- For each tracked vehicle, compute the displacement between consecutive frames in pixels, then convert to a real-world speed estimate using a per-camera calibration factor such as pixels-per-meter or lane geometry.
- Aggregate the median speed of tracked vehicles over the burst.
- Normalize the result against a per-camera free-flow baseline (for example: typical speed at 00:00–06:00 on the same camera, or a generic free-flow speed for that road class).
- Convert this into a traffic score where:
  - free-flow speed => low congestion score,
  - near-stall motion => high congestion score,
  - very slow motion with dense occupancy => highest congestion score.

This is the core change needed to move from “how many vehicles are visible?” to “how slowly is traffic moving?”

A practical blending formula is:

- score = 0.6 * speed_score + 0.4 * occupancy_score
- where speed_score is based on the ratio of current median speed to free-flow speed,
- and occupancy_score is derived from ROI coverage, detection count, and confidence.

This better reflects the semantics used by live map services and reduces false positives caused by a camera seeing many vehicles that are still moving normally.

#### 4A.2 Time-of-day and day-of-week baselines

A fixed threshold is not sufficient for a citywide traffic layer because rush hour and off-peak traffic naturally differ.

- Build rolling baselines per camera for each hour-of-day and weekday pattern.
- Store values like median vehicle count, median speed, median occupancy, and standard deviation for the previous N weeks of observations.
- Compare the current reading to the same camera's normal baseline at that time.
- This allows the UI to say “this is unusually slow for 8:30 AM on a weekday” instead of “this is heavy for this camera all the time.”

The project already contains rolling baseline logic in [src/trafficcam/analysis/baseline.py](../src/trafficcam/analysis/baseline.py) and anomaly detection in [src/trafficcam/analysis/trends.py](../src/trafficcam/analysis/trends.py). The next step is to feed those baseline values back into the main per-camera scoring function so the map color reflects relative traffic conditions, not absolute counts alone.

#### 4A.3 Persistent multi-frame tracking and better motion estimates

The tracker should be maintained across more than a single burst window when possible.

- Keep a lightweight persistent tracker per camera across consecutive capture cycles.
- Track vehicles over multiple 1-second bursts to estimate movement for longer windows.
- Use the aggregated motion profile from the previous 3–5 capture cycles to smooth out jitter.
- This reduces false spikes from a single noisy frame and makes speed estimates more stable.

The tracker is currently used primarily for line-crossing logic. A second use-case should be added: vehicle speed estimation and motion consistency scoring. This can feed both the congestion score and the traffic-layer coloring.

#### 4A.4 Per-camera calibration and lane-aware scoring

Global thresholds will always be limited because each camera has different perspective, distance, lane width, and visible road geometry.

- Use the existing per-camera threshold configuration in `config/camera_density_thresholds.json` as the first calibration layer.
- Add a per-camera free-flow speed calibration constant and a lane weighting model.
- Partition each ROI into meaningful regions, such as near-lane / mid-lane / far-lane bands, and weight each band differently so distant vehicles do not contribute the same as close vehicles.
- Compute lane occupancy and average speed separately for each section and aggregate them.

This is especially important in Macau where a camera may cover a wide road segment with multiple lanes, grade changes, or heavy occlusion at long distances.

#### 4A.5 Better confidence and uncertainty handling

Low-light, rainy, or partially occluded frames should not trigger a false jam reading.

- If scene classification marks the image as night, rain, fog, or low visibility, lower confidence in the speed estimate and widen the acceptable range.
- Only emit a severe traffic warning when both occupancy and speed are bad at the same time.
- If confidence is too low, prefer a neutral state (“unknown / degraded”) instead of a misleading red state.

This complements the existing scene classifier and low-confidence downgrades already present in the pipeline.

#### 4A.6 Road-segment aggregation for map overlays

The dashboard should eventually render not just point markers but traffic conditions for road segments.

- Group nearby cameras into corridor-level segments.
- Average their congestion scores into a corridor score.
- Draw a polyline or colored road overlay between the segment endpoints.
- Use two or three traffic colors (green / orange / red) instead of a raw marker dot.

This is the closest step to a Google Maps-like traffic layer: a road segment estimate rather than a camera point estimate. A point marker is still useful for per-camera detail, but the city overlay should be segment-centric.

#### 4A.7 Temporal smoothing and UX polish

Traffic layers should avoid flickering between states from single noisy readings.

- Use a rolling median of the last 3–5 snapshots before publishing the displayed state.
- Apply small cooldowns when a camera transitions between states to reduce animations from single-frame blips.
- Keep a `last_updated` timestamp and a `confidence` field for the map overlay so the UI can degrade gracefully.

#### 4A.8 Recommended implementation order

1. add speed estimation from tracked motion,
2. blend speed + occupancy into a continuous congestion score,
3. replace zero-shot fixed thresholds with camera-specific baselines,
4. persist per-camera free-flow and baseline calibration data,
5. add corridor aggregation to map rendering,
6. smooth and expose the final traffic layer in the dashboard.

This staged approach keeps the project incremental while steadily pushing the system toward a useful traffic overlay rather than a simple camera alarm list.

### Phase 5 — Storage and API

Goal: expose the data in a simple way.

Tasks:
- save results to JSON files first, then optionally move to a database,
- expose a minimal API for latest frames, camera status, and recent analysis,
- provide a small dashboard or basic web view.

---

## 5. Skeleton file responsibilities

### Core package

- [src/trafficcam/__init__.py](../src/trafficcam/__init__.py)
  - mark the package as the main application namespace,
  - expose version and entry-point helpers if needed.

- [src/trafficcam/cli.py](../src/trafficcam/cli.py)
  - provide the command-line interface for discovery, capture, analysis, and API startup,
  - keep CLI flags aligned with the current [macau_dsat_feed.py](../macau_dsat_feed.py) workflow.

- [src/trafficcam/config.py](../src/trafficcam/config.py)
  - load environment variables and defaults,
  - hold DSAT URLs, output directories, ffmpeg settings, API host/port, and retry thresholds.

- [src/trafficcam/models.py](../src/trafficcam/models.py)
  - define data classes or Pydantic models for cameras, streams, capture results, analysis results, and health records.

### Ingestion module

- [src/trafficcam/ingestion/__init__.py](../src/trafficcam/ingestion/__init__.py)
  - re-export the ingestion helpers.

- [src/trafficcam/ingestion/dsat_client.py](../src/trafficcam/ingestion/dsat_client.py)
  - handle HTTP fetching of DSAT pages,
  - follow reload/redirect mechanisms,
  - extract camera links and stream URLs,
  - return normalized camera feed definitions.

- [src/trafficcam/ingestion/manifest_builder.py](../src/trafficcam/ingestion/manifest_builder.py)
  - build a manifest from discovered camera data,
  - sort or filter cameras by name or location,
  - save the manifest to disk in a reusable format.

- [src/trafficcam/ingestion/schemas.py](../src/trafficcam/ingestion/schemas.py)
  - hold any parsing-specific data structures used during ingestion.

### Capture module

- [src/trafficcam/capture/__init__.py](../src/trafficcam/capture/__init__.py)
  - expose capture helpers and common constants.

- [src/trafficcam/capture/frame_capturer.py](../src/trafficcam/capture/frame_capturer.py)
  - orchestrate frame capture jobs for one or many cameras,
  - handle looped capture and output directory creation,
  - emit capture results and store metadata.

- [src/trafficcam/capture/ffmpeg_runner.py](../src/trafficcam/capture/ffmpeg_runner.py)
  - wrap the ffmpeg execution logic,
  - run one-shot frame extraction and handle errors cleanly.

- [src/trafficcam/capture/retry_policy.py](../src/trafficcam/capture/retry_policy.py)
  - define retry, backoff, and timeout behavior for flaky feeds.

### Analysis module

- [src/trafficcam/analysis/__init__.py](../src/trafficcam/analysis/__init__.py)
  - expose analysis entry points.

- [src/trafficcam/analysis/traffic_detector.py](../src/trafficcam/analysis/traffic_detector.py)
  - inspect a captured frame and produce a traffic-level estimate such as light, moderate, heavy, or blocked.

- [src/trafficcam/analysis/scene_classifier.py](../src/trafficcam/analysis/scene_classifier.py)
  - classify scene context such as day/night, rain, fog, or low visibility.

- [src/trafficcam/analysis/baseline.py](../src/trafficcam/analysis/baseline.py)
  - compute rolling, hour-bucketed baselines for incident detection.

- [src/trafficcam/analysis/coalesce.py](../src/trafficcam/analysis/coalesce.py)
  - group sustained anomalies into single coalesced incident alerts.

- [src/trafficcam/analysis/trends.py](../src/trafficcam/analysis/trends.py)
  - detect congestion runs, incident anomalies, and directional flow splits over persisted history.

- [src/trafficcam/analysis/metrics.py](../src/trafficcam/analysis/metrics.py)
  - calculate simple summary statistics from multiple frames over time.

### Storage module

- [src/trafficcam/storage/__init__.py](../src/trafficcam/storage/__init__.py)
  - expose the storage interfaces.

- [src/trafficcam/storage/base.py](../src/trafficcam/storage/base.py)
  - define the abstract repository interface for storing manifests, captures, and analysis results.
  - define JSONL append/load/save behavior for index files.

- [src/trafficcam/storage/json_store.py](../src/trafficcam/storage/json_store.py)
  - provide a simple file-based implementation for the first version,
  - store JSON snapshots of cameras, captures, and analysis data in a local data directory,
  - support JSONL index append and load operations.

- [src/trafficcam/storage/index.py](../src/trafficcam/storage/index.py)
  - maintain compact per-camera analysis indices for fast record loading.

- [src/trafficcam/storage/database.py](../src/trafficcam/storage/database.py)
  - optionally add SQLAlchemy or SQLite support later for richer querying.

### API and web module

- [src/trafficcam/api/__init__.py](../src/trafficcam/api/__init__.py)
  - mark the API package.

- [src/trafficcam/api/main.py](../src/trafficcam/api/main.py)
  - initialize the FastAPI app and register routes.

- [src/trafficcam/api/routes.py](../src/trafficcam/api/routes.py)
  - expose endpoints for camera lists, latest frame metadata, analysis summaries, and health status.

- [src/trafficcam/web/__init__.py](../src/trafficcam/web/__init__.py)
  - mark the web package.

- [src/trafficcam/web/app.py](../src/trafficcam/web/app.py)
  - provide a very lightweight dashboard or API bridge for viewing cameras and recent results.

---

## 6. Test plan

Tests should cover both unit-level behavior and real-world behavior.

### Unit tests

- [tests/unit/test_dsat_client.py](../tests/unit/test_dsat_client.py)
  - verify that the DSAT client can parse sample pages and resolve the correct feed URLs.

- [tests/unit/test_manifest_builder.py](../tests/unit/test_manifest_builder.py)
  - verify that manifest generation produces the expected JSON structure.

- [tests/unit/test_frame_capturer.py](../tests/unit/test_frame_capturer.py)
  - verify frame capture output, timing, and metadata persistence.

- [tests/unit/test_trends.py](../tests/unit/test_trends.py)
  - verify congestion detection, incident detection, and persistence of incident alerts.

- [tests/unit/test_baseline.py](../tests/unit/test_baseline.py)
  - verify rolling-window and hour-bucket baseline behavior.

- [tests/unit/test_json_store_index.py](../tests/unit/test_json_store_index.py)
  - verify JSONL index append/load behavior and prefix-safe record listing.

- [tests/unit/test_coalesce.py](../tests/unit/test_coalesce.py)
  - verify cooldown-based incident grouping.

  - verify frame capture logic, output directory handling, and capture metadata.

- [tests/unit/test_analysis.py](../tests/unit/test_analysis.py)
  - verify the traffic classification and scene analysis outputs.

### Integration tests

- [tests/integration/test_live_capture.py](../tests/integration/test_live_capture.py)
  - exercise the real DSAT site and confirm that frames can be captured from multiple feeds.

- [tests/integration/test_api.py](../tests/integration/test_api.py)
  - verify the API endpoints return valid responses.

### Fixtures

- [tests/fixtures/dsat_index.html](../tests/fixtures/dsat_index.html)
  - sample HTML from the DSAT index page for parser tests.

- [tests/fixtures/dsat_detail.html](../tests/fixtures/dsat_detail.html)
  - sample HTML or response content for camera page parsing tests.

---

## 7. Migration approach for the current repo

The current code should not be thrown away. Instead:

1. keep [macau_dsat_feed.py](../macau_dsat_feed.py) as the compatibility entry point,
2. move the real logic into the new package under [src/trafficcam](../src/trafficcam),
3. keep the current CLI behavior available through the new package,
4. add tests before changing the behavior of the older script.

This keeps the work incremental and reduces the risk of breaking the existing live-feed proof-of-concept.

---

## 8. Suggested delivery order

1. Create the package structure and core models.
2. Move DSAT discovery logic into the ingestion module.
3. Move frame capture logic into the capture module.
4. Add simple analysis and persistence layers.
5. Expose results through a minimal API.
6. Add a small dashboard and deploy via Docker.

---

## 9. Current project checklist

Status as of 2026-08-25:

- [x] camera map editing is available in the dashboard and manual placements persist to `config/camera_coordinates.json`
- [x] traffic scoring now blends occupancy and motion-derived speed estimates instead of relying on a single occupancy proxy
- [x] per-camera motion calibration and free-flow baselines are implemented in `tools/calibrate_freeflow.py` and `src/trafficcam/vision/speed_estimator.py`
- [x] time-of-day and hour-of-week baseline adjustments are implemented in `src/trafficcam/analysis/temporal.py`
- [x] the run-once pipeline in `scripts/run_e2e_pipeline.py` now emits speed-aware congestion and temporal adjustment metadata
- [x] focused validation covered detector regression, speed estimation, free-flow calibration, and temporal scoring checks
- [x] the dashboard work is active on the current branch and includes camera map editing, dashboard summary cards, and route-level detail panels
- [x] the API and dashboard now include a lightweight corridor overlay derived from nearby cameras in the same district/sub-district cluster
- [ ] populate live calibration values from additional sustained motion history once more real-world data is collected
- [ ] turn the current heuristic corridor overlay into a config-backed road-segment model for production-like traffic-layer geometry
- [ ] continue the API/UI polish and richer dashboard integration for drill-down and camera detail views
- [ ] add more end-to-end coverage around live camera coordinates, map rendering, and UI response flows

## 10. Current progress tracker

This repo already includes the following completed work:

- [x] package structure created under `src/trafficcam`
- [x] compatibility wrapper retained in `macau_dsat_feed.py`
- [x] DSAT ingestion logic moved into `src/trafficcam/ingestion/dsat_client.py`
- [x] reload/continue anti-bot handling added for `realtime_reload.aspx` / `realtime_core4.aspx`
- [x] frame capture flow moved into `src/trafficcam/capture/frame_capturer.py`
- [x] simple `ffmpeg` wrapper added in `src/trafficcam/capture/ffmpeg_runner.py`
- [x] unit tests and integration tests added under `tests/`
- [x] utility scripts placed in `tools/` for live site probing and page inspection
- [x] Docker support updated to include the new package layout and dependencies
- [x] README updated to document the current state and live probe workflow
- [x] analytical scoring, time-of-day baselines, and speed-aware calibration work are now part of the main pipeline and validation flow
- [x] the live dashboard branch has working camera visualization, summary cards, and a lightweight corridor overlay for road-segment style map rendering

Work still to do:

- [x] implement the analysis pipeline in `src/trafficcam/analysis/`
- [x] implement speed-based traffic scoring and motion-aware congestion estimation (see `src/trafficcam/vision/speed_estimator.py`; blended via `DensityScorer.score(speed_component=...)`, wired into `scripts/run_e2e_pipeline.py`)
- [x] add time-of-day baselines for traffic severity (implemented in `src/trafficcam/analysis/temporal.py`; applied to main scoring in `scripts/run_e2e_pipeline.py`)
- [x] add a first-pass corridor overlay to the dashboard and overview payloads (`src/trafficcam/api/routes.py` + `src/trafficcam/web/map_page.py`)
- [ ] complete per-camera calibration rollout for traffic severity using sustained live motion history
- [ ] implement storage persistence beyond simple JSON storage
- [ ] finish API routing and connect it to the persisted results and dashboard data model
- [ ] complete the basic web dashboard and map overlays in `src/trafficcam/web/`
- [ ] convert the current corridor overlay into a config-backed road-segment model for a more production-like traffic layer
- [ ] add richer integration tests for API and UI behavior
- [ ] refine the capture retry policy and error handling

The project is now past the initial prototype stage. The main work remaining is operationalizing the calibrated scoring model into a more polished map/dashboard experience, with live calibration and a more explicit corridor/road model as the next major follow-ups before a production-like traffic layer is ready.

## 11. Immediate next actions

For the next work session, the best next move is:

1. collect and validate more live motion history so per-camera calibration values can be populated from real data rather than heuristic defaults;
2. replace the current district-based corridor heuristic with a config-backed road-segment model, using explicit camera groupings or corridor definitions;
3. wire the segment model into the overview API and map rendering as the primary traffic-layer overlay, while keeping the per-camera detail markers as the drill-down view;
4. add a focused regression check covering the segment model and the dashboard/overview payload.

This keeps the project moving from a solid dashboard prototype toward a more realistic traffic-layer experience without overbuilding the architecture before the calibration data is trustworthy.

---

## 10. Notes for implementation

- Keep the first version lightweight and deterministic.
- Prefer file-based storage first; add a database only when query complexity grows.
- Preserve the current Docker-based workflow so the project remains easy to run and test.
- Treat DSAT as an external live source and keep the parser resilient to page changes.
