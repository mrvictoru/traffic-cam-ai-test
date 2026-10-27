# Human calibration runbook

This project currently provides live **provisional** traffic estimates. It is
not yet a Google-Maps-like traffic layer because only 6 of 111 camera positions
are verified. Camera 71 has an initial YOLO11s relative-motion baseline;
other cameras remain uncalibrated, and the baseline is not a physical speed.

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

## 5. Collect reviewed free-flow motion history

The default sample window is **02:00-05:00 Asia/Macau** (18:00-21:00 UTC on the
previous date), because it is a useful quiet-traffic proxy. It is not a
technical requirement. Samples from any local-time window may be considered
when a person verifies that observed vehicles are moving freely. Empty scenes,
queues, red-light stops, and slow/stopped traffic are not free-flow evidence.

Use at least 30 frames per burst at 5 FPS (about 5.8 seconds) and multiple
bursts per camera. Calibration also screens each analysis record using
provisional defaults of mean detector confidence >= 0.25 and at least 2
eligible tracks (track histories long enough for a speed estimate). These are
data-quality filters, not measured accuracy guarantees.
Keep the detector, tracker, FPS, and model version the same between capture
and the pipeline that will use the baseline.
The configured YOLO default is YOLO11s (`yolo11s.pt`). Confirm each persisted
analysis record's `details.detector_model` before combining it with other
history; do not mix models when estimating a baseline.
The legacy `--min-active-tracks` CLI spelling and `min_active_tracks` report
field remain aliases for compatibility; both now refer to the minimum
speed-eligible track count, not the tracker’s raw active-track count.

For a complete collection run:

```bash
docker compose --profile capture up --build
```

For a bounded test run:

```bash
docker compose --profile capture run --no-deps live-capture run-once \
  --frame-count 30 \
  --manifest-file data/manifest.json \
  --output-dir output/live \
  --data-dir data
```

The calibrator defaults to the quiet-traffic proxy, but accepts another
Asia/Macau hour window when the footage has been reviewed. For example, use
`--window-start 10 --window-end 13` to select 10:00-13:00. The legacy
`--offpeak-start` and `--offpeak-end` spellings remain accepted.

During heavy rain, do not use the affected frames for calibration review.
Rain streaks, glare, reflections, spray, and wipers can reduce detector
confidence and make vehicle boxes or lane boundaries unreliable. Record the
weather condition with the capture and repeat the geometry check in a clear
daylight window. Rain-affected observations may remain visible as provisional
live data, but they should not be used to establish a baseline.

## 6. Preview and persist free-flow calibration (automated, review required)

Preview quality-screened cameras for the default window:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  calibrate-freeflow --data-dir data --min-history 10 \
  --min-mean-confidence 0.25 --min-eligible-tracks 2 --dry-run --pretty
```

For a reviewed alternate window, add its local hours, for example:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  calibrate-freeflow --data-dir data --window-start 10 --window-end 13 \
  --min-history 10 --min-mean-confidence 0.25 --min-eligible-tracks 2 \
  --dry-run --pretty
```

The preview reports accepted/rejected records, median and p95 speeds, and p95
values for the chronological halves of the sample. Review those diagnostics
and the corresponding footage before persisting. A candidate can meet the
minimum sample count and still be unstable; there is not yet a validated
cross-window stability tolerance. If the preview is acceptable, rerun the
same command without `--dry-run` to persist the baselines:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  calibrate-freeflow --data-dir data --min-history 10 \
  --min-mean-confidence 0.25 --min-eligible-tracks 2 --pretty
```

The default calibration filters for `yolo11s.pt` records and stores that model
identifier with each baseline. Use `--detector-model` only when intentionally
calibrating another exact model; records with absent or different model
metadata are excluded.

Then audit the rollout:

```bash
docker compose exec macau-feed python -m trafficcam.cli \
  audit-config --pretty --report-file output/config-audit.json
```

The stored baseline is camera-relative pixels per sampled frame, not km/h.
Physical speed requires separate camera geometry calibration and measured
reference distances. The dashboard should only label a camera **reliable**
when its observation is fresh, its detector confidence is adequate, and a
free-flow baseline is configured. Fresh observations without calibration
remain **provisional**.

## Historical checkpoint status

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
- All traffic remained provisional at that checkpoint until valid free-flow
  history was captured and calibrated.
- Heavy rain is a data-quality warning: postpone calibration and repeat the
  capture in clear conditions rather than treating rain-affected detections as
  normal traffic.

Do not commit generated `calib_out.txt`, `final_out.txt`, or
`mounted_final.txt`.
