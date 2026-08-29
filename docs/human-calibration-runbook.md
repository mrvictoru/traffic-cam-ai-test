# Human calibration runbook

This project currently provides live **provisional** traffic estimates. It is
not yet a Google-Maps-like traffic layer because only 6 of 111 camera positions
are verified and no camera has a persisted free-flow speed baseline.

Do the steps below in order. The dashboard exposes the same checklist in the
`Human calibration required` panel and in the `/api/overview` payload.

## 1. Place camera markers on the real roads (human)

There are currently 103 approximate camera positions. Approximate positions
are deliberately hidden by default so the map does not imply false road
accuracy.

1. Start the API with `docker compose up --build`.
2. Open `http://localhost:8000`.
3. Enable **Approx markers**.
4. Enable **Edit positions**.
5. Drag each camera marker to the actual camera/road position.
6. Confirm the saved position remains correct after a page refresh.

The dashboard writes verified positions to
`config/camera_coordinates.json`. Review the file before committing changes.
Only enable a corridor after all of its cameras have verified positions and
the camera order follows the road.

## 2. Draw roadway regions of interest (human)

ROIs prevent the detector from counting sky, buildings, sidewalks, or an
adjacent road. A person must inspect a representative live frame for each
camera and edit `config/camera_rois.json`.

Each polygon should cover the visible travel lanes and exclude non-road
areas. Do not copy one camera's polygon to another camera unless the framing
is genuinely identical.

## 3. Draw flow lines (human)

Directional counts require a line crossing the lanes of travel. Edit
`config/camera_flow_lines.json` for each camera where directional flow is
needed. The line must cross the roadway, not the camera housing, sky, or a
static background edge.

The coordinate format is normalized from 0.0 to 1.0:

```json
{
  "51": {
    "start": [0.0, 0.52],
    "end": [1.0, 0.52]
  }
}
```

## 4. Verify corridor geometry (human)

Three conservative corridors are enabled: Outer Harbour Terminal, Friendship
Bridge, and Nam Van Junctions. Four named candidates remain disabled until
their geometry is checked:

- Guia Tunnel
- Sai Van Bridge
- Qingmao Port
- Avenida do Ouvidor Arriaga

Verify the camera positions, direction of travel, and camera order in
`config/camera_corridors.json` before setting `enabled` to `true`. Do not use
long point-to-point chords as a substitute for verified road geometry.

## 5. Collect free-flow motion history (automated, time-gated)

Free-flow calibration only accepts motion samples captured from **02:00 to
05:00 Asia/Macau**. This is 18:00 to 21:00 UTC on the previous date.

Capture at least five frames per camera. Five frames allow the simple tracker
to estimate motion; a one-frame capture can refresh occupancy but cannot
provide a useful speed sample.

For a complete collection run:

```bash
docker compose --profile capture up --build
```

For a bounded test run:

```bash
docker compose --profile capture run --no-deps live-capture run-once \
  --frame-count 5 \
  --manifest-file data/manifest.json \
  --output-dir output/live \
  --data-dir data
```

Daytime and evening captures are still useful for current occupancy, but they
must not be treated as free-flow speeds.

During heavy rain, do not use the affected frames for calibration review.
Rain streaks, glare, reflections, spray, and wipers can reduce detector
confidence and make vehicle boxes or lane boundaries unreliable. Record the
weather condition with the capture and repeat the geometry check in a clear
daylight window. Rain-affected observations may remain visible as provisional
live data, but they should not be used to establish a baseline.

## 6. Preview and persist free-flow calibration (automated)

Preview the cameras that have enough valid off-peak motion history:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  calibrate-freeflow --data-dir data --dry-run --pretty
```

Only after reviewing the dry-run output, persist the baselines:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  calibrate-freeflow --data-dir data --pretty
```

Then audit the rollout:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  audit-config --pretty --report-file output/config-audit.json
```

The dashboard should only label a camera **reliable** when its observation is
fresh, its detector confidence is adequate, and a free-flow baseline is
configured. Fresh observations without calibration remain **provisional**.

## Current checkpoint status

At the 2026-08-29 calibration pass:

- 111 cameras are in the manifest.
- 30 cameras have motion-aware analyses from the bounded capture run.
- A free-flow dry-run found 0 eligible cameras: those 30 records were outside
  02:00-05:00 Asia/Macau and the other 81 cameras had no motion history.
- 25 roadway ROIs and 21 unambiguous flow lines were manually reviewed against
  `output/live/cam_<id>/frame_005.jpg`.
- Cameras 60, 61, 62, 63, and 69 were deliberately deferred because blur,
  construction, complex geometry, or glare made a defensible calibration
  impossible. Flow lines 49, 73, 79, and 82 were also deferred because one
  line would mix multiple traffic movements.
- 8 named camera positions were verified; 103 remained approximate. Cameras
  60 and 62 were added from exact OpenStreetMap named-place results; ambiguous
  road-only geocoding results were rejected.
- 3 corridors were enabled and live; 4 remained disabled.
- All traffic remains provisional until valid off-peak free-flow history is
  captured and calibrated.
- Heavy rain is a data-quality warning: postpone calibration and repeat the
  capture in clear conditions rather than treating rain-affected detections as
  normal traffic.

Do not commit generated `calib_out.txt`, `final_out.txt`, or
`mounted_final.txt`.
