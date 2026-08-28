# Human calibration runbook

This project currently provides live **provisional** traffic estimates. It is
not yet a Google-Maps-like traffic layer because only 6 of 111 camera positions
are verified and no camera has a persisted free-flow speed baseline.

Do the steps below in order. The dashboard exposes the same checklist in the
`Human calibration required` panel and in the `/api/overview` payload.

## 1. Place camera markers on the real roads (human)

There are currently 105 approximate camera positions. Approximate positions
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

At the end of the 2026-08-28 session:

- 111 cameras are in the manifest.
- 30 cameras had fresh analyses from the bounded capture run.
- All 30 were provisional; 0 were reliable or calibrated.
- 81 cameras had no current analysis.
- 6 camera positions were verified; 105 remained approximate.
- 3 corridors were enabled and live; 4 remained disabled.
- The off-peak window was closed when the session stopped.

Do not commit generated `calib_out.txt`, `final_out.txt`, or
`mounted_final.txt`.
