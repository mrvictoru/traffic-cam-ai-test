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

Status as of 2026-09-27:

- [x] camera map editing is available in the dashboard and manual placements persist to `config/camera_coordinates.json`
- [x] traffic scoring now blends occupancy and motion-derived speed estimates instead of relying on a single occupancy proxy
- [x] per-camera motion calibration and free-flow baselines are implemented in `tools/calibrate_freeflow.py` and `src/trafficcam/vision/speed_estimator.py`
- [x] time-of-day and hour-of-week baseline adjustments are implemented in `src/trafficcam/analysis/temporal.py`
- [x] the run-once pipeline in `scripts/run_e2e_pipeline.py` now emits speed-aware congestion and temporal adjustment metadata
- [x] focused validation covered detector regression, speed estimation, free-flow calibration, and temporal scoring checks
- [x] the dashboard work is active on the current branch and includes camera map editing, dashboard summary cards, and route-level detail panels
- [x] the API and dashboard now include a lightweight corridor overlay derived from nearby cameras in the same district/sub-district cluster
- [x] `/api/overview` exposes a `calibration_summary` block and the dashboard shows configured/ready/need-history counts so rollout progress is visible at a glance
- [x] an `audit-config` pass confirmed all 9,646 legacy records predate the speed-aware pipeline commit, so fresh live motion collection is the gating factor for backfill — not code
- [x] rebuild the service with CPU-only Torch wheels and verify CUDA is not installed or selected
- [x] validate live speed capture on camera 51; sparse ByteTrack bursts produced no identities, while the simple tracker at 5 FPS produced a `9.53 px/frame` motion sample
- [x] set the sparse-burst defaults to the simple tracker and 5 FPS while keeping Supervision available as an explicit override
- [x] interpret the configurable calibration sample window in `Asia/Macau` local time instead of comparing UTC `Z` timestamps directly
- [x] add direct Leaflet-page render coverage for corridor and calibration payloads
- [x] commit and push the validated checkpoint as `980371c` on `copilot/build-web-ui-for-map-visualization`
- [x] inspect the live dashboard against `/api/overview` and `/api/cameras`: 111 cameras, 3 green corridors, and matching summary cards/markers
- [x] remove the hardcoded `PIPELINE_AUTOSTART=1` runtime bottleneck, make the default Compose service API-only, and expose live capture through an explicit `capture` profile
- [x] add explicit traffic reliability metadata and live-coverage aggregates so stale, uncalibrated, and missing observations are not presented as routing-grade live traffic
- [x] make the dashboard suppress stale congestion colours and scores, grey out historical corridors, and explain live coverage/calibration limitations in a prominent status banner
- [x] surface an explicit human-vs-automated calibration checklist on `/api/overview` and the dashboard so placement, ROI, corridor, and free-flow sample quality work are not mistaken for finished live traffic
- [x] manually review the saved 2026-08-28 five-frame bursts and add 25 roadway ROIs plus 21 unambiguous single-road flow lines; record five unusable views and four complex intersections as deliberately deferred in `config/camera_geometry_review.json`
- [x] cross-check the reviewed geometry against 24 successfully captured daylight frames and add exact named-place coordinates for cameras 60 and 62; reject ambiguous road-only geocoding matches
- [ ] populate live calibration values only after quality-screened, visually reviewed samples are stable across independent collection periods; 02:00-05:00 Asia/Macau is a quiet-traffic proxy, not a hard time requirement
- [x] replace heuristic corridor grouping with an explicit config-backed camera corridor model in `config/camera_corridors.json`
- [x] populate the first conservative corridor groupings from named DSAT cameras and manually verified coordinates (58-59, 51-52, and 49-50)
- [x] catalog four additional named-road candidates (Guia Tunnel, Sai Van Bridge, Qingmao Port, and Avenida do Ouvidor Arriaga) as disabled until their camera positions and road order are verified
- [x] validate enabled/disabled corridor behavior with 17 focused API tests
- [ ] verify road geometry and expand `config/camera_corridors.json` for the remaining cameras
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
- [x] finish the initial API routing and connect it to persisted results and the dashboard data model
- [x] complete the basic web dashboard and first-pass map overlays in `src/trafficcam/web/`
- [ ] continue API/UI polish for richer drill-down and camera detail workflows
- [x] convert corridor grouping to a config-backed model (`config/camera_corridors.json`) and populate three conservative first-pass groupings
- [ ] verify richer road geometry and expand the corridor catalog beyond the first six positioned cameras
- [ ] add richer integration tests for API and UI behavior
- [ ] refine the capture retry policy and error handling

The project is now past the initial prototype stage. The main work remaining is operationalizing the calibrated scoring model into a more polished map/dashboard experience, with live calibration and a more explicit corridor/road model as the next major follow-ups before a production-like traffic layer is ready.

## 11. Immediate next actions

Status update 2026-08-28: an `audit-config` run over the persisted history
confirmed that none of the 9,646 existing analysis records contain
`median_speed_px_per_frame` because they all predate the speed-aware scoring
commit. The rollout therefore needs fresh motion data before free-flow values
can be computed — no code change can backfill from this history.

Live dashboard validation on the same checkpoint confirmed that the rendered
page agrees with the API payload: 111 cameras, average score 3.5, 3 green
corridor polylines, and 105 approximate camera positions. Only 6 cameras have
verified coordinates, so the remaining markers currently form coarse district
clusters rather than a reliable road map. Calibration is still 0 configured,
with 30 cameras having motion records but no usable off-peak history and 81
having no history. The dashboard's `Need history` card currently shows 0 because
it only counts `insufficient_history`; the detailed calibration payload is the
authoritative breakdown.

### 2026-09-26 motion-calibration capture

Thirty-four 30-frame bursts were collected for camera 71 and fifteen for
cameras 49, 51, 58, and 75 using YOLO11s, the simple tracker, and 5 FPS. In a
reviewed 12:00-16:00 Asia/Macau dry-run, camera 71 had 23 retained samples
(p95 8.413 px/sample-frame; chronological-half p95 ratio 1.056). Frames showed
vehicles moving through the scene. That single-camera relative-motion baseline
was persisted as an initial pilot. Camera 49's half-period ratio was 2.038;
cameras 51, 58, and 75 had too few acceptable records or strongly divergent
halves, so no values were promoted for them. These values are not
physical-speed ground truth. The active YOLO model default is now YOLO11s, and
calibration records and stored baselines are model-tagged to prevent mixing
different detector versions.

The calibration workflow now needs confidence/track-quality screening,
transparent rejected-sample and split-period diagnostics, and truthful local
sampling-window metadata. The 02:00-05:00 period is a quiet-traffic proxy, not
a mandatory capture time. The baseline remains pixels per sampled frame.

The normal Compose service is now API-only with `PIPELINE_AUTOSTART=0`. Live
capture runs in a separate `live-capture` service through the explicit
`capture` profile (`docker compose --profile capture up`), so model inference
cannot starve Uvicorn. Dashboard loading was also moved away from recursive
request-time scans of all 9,646 analysis files: startup warms only the latest
record per camera, while calibration coverage refreshes in the background.
After the service reported healthy, measured response times were 0.16 seconds
for `/`, 0.06 seconds for `/api/cameras`, and 0.11 seconds for `/api/overview`.

The dashboard now treats a traffic observation as live only for 20 minutes.
Current API output correctly reports zero live cameras for the persisted
2026-08-27 data instead of rendering those old scores as a green live traffic
layer. Fresh but uncalibrated observations are labelled provisional; only
fresh, calibrated observations with adequate detector confidence are labelled
reliable. This improves honesty and readability, but routing-grade accuracy
still depends on quality-screened, visually reviewed free-flow motion history
and completing per-camera calibration.

Human work that cannot be automated:

- place the remaining approximate cameras (currently 103 of 111) with **Edit
  positions** or `config/camera_coordinates.json`;
- draw roadway ROIs and flow lines in `config/camera_rois.json` and
  `config/camera_flow_lines.json`;
- verify and enable the four disabled named corridors after checking camera
  order and geometry.

Automated work that requires suitable footage:

1. use the same detector, tracker, and capture FPS that the target pipeline will use;
2. collect repeated bursts of at least 30 frames per camera while vehicles are visibly moving freely. 02:00–05:00 Macau local time is a quiet-traffic proxy; other manually reviewed windows are supported;
3. run `python -m trafficcam.cli calibrate-freeflow --data-dir data --dry-run` to inspect accepted/rejected evidence and chronological-half p95 stability before persisting values into `config/camera_speed_calibration.json`;
4. run `python -m trafficcam.cli audit-config` to confirm `speed_calibration.configured_count` and the dashboard calibration checklist reflect quality-qualified history.

The current calibration defaults screen for at least 10 retained bursts,
mean confidence >= 0.25, and at least 2 evaluated, speed-eligible track
histories. Legacy records without an explicit eligibility evaluation are
rejected rather than treating all active tracks as usable motion evidence.
These operational filters are provisional rather than accuracy guarantees.
The calibration report exposes chronological-half p95 values; no validated cross-window
stability tolerance has been established, so an operator must review the
report and footage before persistence. Baselines remain relative pixels per
sampled frame, not physical speeds.

### 2026-09-26 evening calibration expansion

An additional 20 bursts each were captured for cameras 49, 51, 58, 71, and 75
in the 16:00-18:00 Asia/Macau window, for 60 total bursts per camera. A dry-run
produced candidates for cameras 49 (31 retained; split p95 ratio 1.213), 51
(22; 1.130), 71 (24; 2.240), and 75 (42; 1.051); camera 58 had no candidate.
These remain review-only evidence, not approved calibration values. Camera 71's
late-window estimate (6.038 px/sample-frame) does not validate its existing
8.413 pilot, and no values from this capture were persisted.

A separate first-pass pilot collected eight 30-frame bursts for cameras 50,
52, 59, 60, 61, 62, 63, 64, 65, and 66 using YOLO11s, the simple tracker, and
5 FPS. The initial dry-run did not meet the 10-retained-sample minimum for any
camera. Camera 62 had the strongest evidence, so 25 more bursts were collected
for that camera. Its 18:00-19:00 dry-run had 30 quality-qualified and 27
retained samples, with a 2.094 px/sample-frame candidate and a split p95 ratio
of 1.180 (15/11 samples); the report still required review.

Camera 59 was also reviewed as a simpler-road pilot. The former ROI spanned
almost the full frame, and the former flow line appeared roughly aligned with
the road. On 2026-09-26 these were revised in `config/camera_rois.json` and
`config/camera_flow_lines.json`: the ROI now follows the visible carriageway
edge, and the count line crosses the road. An overlay was checked against
three early-evening sample frames. The eight existing bursts yielded seven
quality-qualified records, four retained samples, and a chronological-half
p95 ratio of 30.737; they predate the geometry change and must not be reused
as post-change calibration evidence. A fresh 30-frame smoke capture confirmed
the pipeline applies the revised ROI and configures the flow line; it observed
zero crossings in that single burst, which is not enough to validate count-line
performance. A fresh post-change night series then collected 20 bursts (30
frames each); all 20 analysis records confirm the ROI was applied. Six records
passed the calibration quality screen, four remained after outlier trimming,
and no candidate met the 10-sample minimum. The split-half p95 ratio was 4.365.
Several representative night frames and existing daylight frames were checked
with the revised overlay, but this series is insufficient for calibration.
Collect additional free-flow bursts under clearer/brighter conditions and
review the line-count behavior over more trajectories. The geometry-review
file's earlier reviewed status does not establish current calibration
suitability.

To check another period, 30 additional camera 62 bursts were captured
separately in the 19:00-20:00 window. The dry-run retained 19 samples from 24
quality-qualified records and estimated 3.078 px/sample-frame. This is about
47% higher than the preceding period; its chronological halves retained 12
and 9 samples and had a p95 ratio of 1.931. The report marks split history
insufficient. Reviewed frames show a junction with buses, pedestrians, and
turning traffic; still frames do not establish free-flow conditions. This is a
separate hour period on the same day, not independent-day validation. No
camera 62 baseline was persisted; camera 71 remains the only configured pilot.
The capture and dry-run artifacts are in
`data/motion-calibration-yolo11s-20260926-expansion-10-corrected/` and
`data/motion-calibration-yolo11s-20260926-camera62-independent-period/`.

Those earlier dry-runs used two screens that hid the actual motion mixture.
Burst-mean confidence counted empty frames as zero, so camera 59 rejected 13
of 20 records for low confidence even when occupied frames were around 0.45.
The old outlier trim also dropped anything above twice the median, which
removed the faster tail whenever most bursts were stopped and then published
the stopped cluster as if it were free-flow. Calibration now screens
occupied-frame confidence when per-frame results exist, keeps a repeated
faster mode instead of treating it as one spike, and refuses to persist a
window whose median is far below its upper tail. Records without per-frame
results still use the burst mean. Camera 71's saved pilot was not rewritten.

Re-screening the existing captures did not produce a baseline. Camera 59's
20:00-22:00 series now has 17 quality-qualified samples, median 0.28 and p95
7.22 px/sample-frame, and is blocked as stopped-dominated. Camera 62's
19:00-20:00 series has 29 quality-qualified samples, median 1.66 and p95
7.308, also stopped-dominated; its 18:00-19:00 series has 31 samples, median
1.227 and p95 3.644, and is blocked the same way. The previews are
`calibration-preview-20-22-mixture-guard.json`,
`calibration-preview-19-20-mixture-guard.json`, and
`calibration-preview-18-19-mixture-guard.json` beside the earlier reports.
No camera 59 or 62 value was persisted.

Capture and analysis succeeded, but these windows are mixed stopped and moving
traffic, not confirmed free-flow. The next collection still needs a period
where vehicles are visibly moving steadily, preferably on camera 59 with the
revised geometry. Do not add a broad camera 62 ROI. Continue to leave the
calibration rollout checklist below unchecked until an independent period is
stable under the mixture guard and visually reviewed.

The 2026-08-29 free-flow dry-run returned zero eligible cameras: 30 cameras
had motion-aware records outside the off-peak window and 81 had no motion
history. No speed calibration was written. A density-threshold dry-run was
also inspected but not persisted because the legacy count distributions were
generated before the newly reviewed ROIs; mixing those counts with the new
geometry would produce misleading thresholds.

Error-path records now carry the same schema as successful ones (null motion
values), so failed analyses no longer produce structurally inconsistent rows.

### 2026-09-26/27 camera 109 live-feed and daytime calibration probe

Camera 109 (`友誼大橋近氹仔端出口`) was reachable through its DSAT HLS stream.
An initial 30-frame probe and ten additional 30-frame night bursts produced
11 healthy records using `yolo11s.pt`. The 20:00-23:00 dry-run candidate was
3.744 px/sample-frame from 11 quality-qualified samples; its chronological
halves contained only five and six samples, below the ten-per-half review
minimum. The earlier loop reused frame paths, so only its last burst image was
retained.

A fresh daytime image and the all-feed contact sheet clarify the scene: camera
109 is one elevated bridge view showing opposing carriageways, not a composite
of independent camera panels. The inventory now classifies it as a corridor
candidate. The active estimator pools track displacement and does not
produce direction-specific speeds. The operator later requested separate
counts and speed baselines for image-left and image-right carriageways; these
are image-relative labels, not verified compass directions. The full-feed
visual inventory is in
`data/camera-feed-inventory-20260927/feed-classification.md`.

On 2026-09-27, 20 additional 30-frame bursts were captured from about
12:32-12:38 Asia/Macau, each with its own output directory and retained frames.
All 20 passed the quality screen. The 12:00-14:00 dry-run candidate is 2.874
px/sample-frame, with median 1.737 and a chronological-half p95 ratio of
1.278 (10 samples in each half). This candidate is about 23% below the prior
evening estimate. The review contact sheet is
`output/camera109-daytime-pilot-20260927/burst-contact-sheet.jpg`; the preview
is `data/camera109-daytime-pilot-20260927/calibration-preview-12-14.json`.

No calibration was persisted. The configured camera 109 ROI and flow-count
line remain unset. A preview-only polygon was reviewed on frames from bursts
01, 10, and 20; it covers both carriageways, trims the top/bottom overlays,
and includes the narrow center divider because the current config supports a
single polygon. Re-analysis of all 600 retained frames with that polygon kept
20/20 samples quality-qualified. The dry-run candidate was 2.902 px/sample-
frame (median 1.706), only about 1% above the full-frame candidate, while the
half-to-half p95 ratio increased from 1.278 to 1.437. Thus the mask has little
effect on the pooled candidate, but the within-period upper-tail difference
and the roughly 23% lower daytime candidate versus the prior evening estimate
still warrant review. The overlay is
`output/camera109-daytime-pilot-20260927/roi-preview-contact-sheet.jpg`, the
polygon is in `data/camera109-daytime-pilot-20260927/roi-candidate-preview.json`,
and ROI re-analysis is in `data/camera109-daytime-pilot-20260927/roi-review/`.
No production ROI, flow line, or speed calibration was written. Obtain another
separated period after the road mask is approved; add a count line only if
crossing counts are required.

### 2026-09-27 camera 109 directional-zone preview

The proposed two-zone overlay was visually reviewed on bursts 01, 10, and 20.
The polygons follow the two visible carriageways, and each candidate line
crosses its own carriageway. Both zones were then analyzed independently over
the same 20 retained daytime bursts, using `yolo11s.pt`; these results remain
preview-only in
`data/camera109-daytime-pilot-20260927/directional-review/`.

Both zones had 20/20 quality-qualified samples. The image-left candidate was
2.243 px/sample-frame (median 1.696; chronological-half p95 ratio 1.133);
the image-right candidate was 3.705 px/sample-frame (median 2.340; ratio
1.040). Each split still has only ten samples per half and is marked
`review_required`. These short, contemporaneous samples are not independent
validation periods and do not establish free-flow conditions, calibrated
physical speed, or production baselines. The observed asymmetry supports
keeping carriageways separate in further evaluation, not interpreting the
candidate values as directly comparable road speeds.

The custom track-history split counted 40 image-left and 46 image-right
crossings across the bursts, each in one image-space polarity. The
`northbound`/`southbound` keys in
`src/trafficcam/analysis/trends.py::compute_directional_flow_split` are
signed-side conventions, not geographic labels. The separate Supervision
`LineZone` counter reported 1 image-left crossing and 4 image-right crossings
across the same bursts, versus 40 and 46 from the custom split. This
disagreement prompted a counter-contract correction in the following
validation. No production multi-zone schema, ROI, count line, or camera 109
calibration has been configured.

### 2026-09-27 camera 109 Sunday afternoon counter validation

Twenty new 30-frame bursts (600 frames total) were captured from camera 109
between 15:07 and 15:12 Asia/Macau at 5 FPS. All 20 captures completed. The
sample is limited to camera 109; it does not establish light traffic across
the wider camera network. The contact sheet is
`output/camera109-sunday-afternoon-20260927/directional-preview-contact-sheet.jpg`,
and the capture metadata and replay results are in
`data/camera109-sunday-afternoon-20260927/`.

On this same sample, the old unbounded centroid split reported image-left
35/1 and image-right 1/39 crossings in its two signed directions, while the
Supervision `LineZone` counter reported zero for both zones. The mismatch was
caused by different rules: the custom split accepted crossings of the
infinite line extension, while Supervision limited the line segment and used
all four bounding-box corners plus a two-frame crossing history.

The directional split now checks that each tracked-centroid segment actually
intersects the configured finite line. `flow_rate_vph`,
`flow_count_per_burst`, `details.line_crossings`, and the final per-frame
crossing snapshot now use this single source. The legacy `in`/`out` and
`northbound`/`southbound` keys share the same line-relative polarity and do
not identify compass directions. Regression tests cover crossings outside
the finite segment and equality of the persisted count views.

After correction, the replay counted image-left 35/1 and image-right 1/21
crossings (`in`/`out`) over the 20 bursts. The right-side reduction from 39
to 21 confirms that infinite-extension crossings were inflating counts.
Per-burst outputs now agree by construction; this does not establish
vehicle-count accuracy against hand labels.

Both directional speed candidates had 20/20 quality-qualified samples.
Image-left was 3.305 px/sample-frame (median 2.117; chronological-half p95
ratio 1.151); image-right was 4.208 (median 2.660; ratio 1.219). Density
labels were mostly light—13 light, 6 moderate, 1 heavy on image-left and 14
light, 6 moderate on image-right—but this is one bridge camera, not a
citywide Sunday survey. Each candidate remains marked `review_required`;
these pixel-motion values are not physical speeds or validated free-flow
baselines. No ROI, flow line, or camera 109 calibration was persisted.

### 2026-09-27 camera 109 manual crossing-event spot check

For a preliminary visual check, four bursts were selected across the two
afternoon windows (bursts 01 and 07 in each window). All 30 frames in each
selected burst were reviewed in paired-carriageway sheets, and each of the
14 crossing events emitted by the tracker in those bursts was reviewed in a
short frame sequence around the crossing. The event candidates are listed in
`data/camera109-manual-review/tracker-event-candidates.json`; review sheets
and event sequences are under
`output/camera109-manual-review-first/` and
`output/camera109-manual-review-second/`.

This is only a visual plausibility spot check, not an accuracy benchmark.
Several candidate centroids move only a few pixels around the line, and
vehicles overlap or are small in the 352x288 source, so a crossing caused by
real vehicle motion cannot always be distinguished confidently from detector
box jitter. More importantly, the sample was selected from bursts that had
pipeline-reported crossings: it cannot measure missed crossings (recall) and
is biased for estimating false-positive rate. No precision, recall, or count
error percentage should be inferred from these 14 event candidates.

The appropriate next validation is an independently annotated sample: select
bursts without regard to pipeline output, label every visible vehicle
crossing (including zero-crossing bursts), and have a second reviewer resolve
ambiguous occlusions. Compare per-direction counts and crossing timestamps
against that ground truth before enabling these lines for production.

A second set of 20 bursts (600 frames) was captured the same afternoon from
15:54 to 16:00. One burst began at 16:00:01, outside the configured
12:00-16:00 candidate window, so 19 image-left and 18 image-right samples
qualified in that period; one additional image-right sample lacked sufficient
track support. The second-period candidates were 3.651 px/sample-frame on
image-left (median 2.071; split-half p95 ratio 1.662) and 3.600 on image-right
(median 2.256; ratio 1.284). Densities were mostly light: 17/20 image-left
and 15/20 image-right.

Comparing the first and second periods, the candidate changed from 3.305 to
3.651 on image-left (+10.5%) and from 4.208 to 3.600 on image-right (-14.4%).
A same-day 12:00-16:00 dry-run using all available samples yielded 3.558 for
image-left (39 qualified samples; combined split-half p95 ratio 1.098) and
4.003 for image-right (38 samples; ratio 1.183). These multi-window
aggregates are more stable than the second image-left window alone, but the
within-window variation and sample-window boundary reinforce that a
preview-derived baseline should not yet be persisted. The second-period
overlay and comparison are
`output/camera109-sunday-afternoon-20260927-1546/directional-preview-contact-sheet.jpg`
and `data/camera109-sunday-afternoon-20260927-1546/directional-comparison.json`.
No production calibration was written.

For later work sessions, the remaining priorities in order:

1. collect fresh, quality-screened free-flow motion history with the target model, rebuild the Docker image if needed, and run the calibration backfill workflow;
2. verify more camera coordinates and road geometry before enabling additional corridors; replace long point-to-point chords with defensible segment paths;
3. wire richer segment geometry into the overview API and map rendering while keeping per-camera markers as the drill-down view;
4. add broader end-to-end coverage for live coordinates, map rendering, detail-panel loading, and UI response flows.

This keeps the project moving from a solid dashboard prototype toward a more realistic traffic-layer experience without overbuilding the architecture before the calibration data is trustworthy.

---

## 12. Notes for implementation

- Keep the first version lightweight and deterministic.
- Prefer file-based storage first; add a database only when query complexity grows.
- Preserve the current Docker-based workflow so the project remains easy to run and test.
- Treat DSAT as an external live source and keep the parser resilient to page changes.
