# Camera 109 Directional Count Validation Guide

## Goal

Establish whether the preview-only image-left and image-right counting lines
produce counts accurate enough for a camera-109 shadow pilot. This is a
validation task, not authorization to enable production counts or save speed
calibrations.

The application counts tracked vehicle centroids crossing a finite line. Its
legacy `northbound`/`southbound` and `in`/`out` fields describe line-relative
polarity, not verified compass directions. Use `image_left` and `image_right`
until the roadway headings have been independently verified.

The 2026-09-28 independent-sample preparation and exploratory replay audit
are documented in [the independent count audit](./camera109-independent-count-audit.md).
It did not produce adjudicated count ground truth or authorize a shadow pilot.

## Existing evidence

Use the retained afternoon captures, not another live capture:

- `data/camera109-sunday-afternoon-20260927/capture-report.json` — 20 bursts
  from approximately 15:07-15:12 Asia/Macau.
- `data/camera109-sunday-afternoon-20260927-1546/capture-report.json` — 20
  bursts from approximately 15:54-16:00 Asia/Macau.
- `data/camera109-sunday-afternoon-20260927/directional-counter-review.json`
  and `data/camera109-sunday-afternoon-20260927-1546/directional-comparison.json`
  — prior preview results. Keep these sealed until the independent labels are
  frozen.

Frames and reports under `data/` and `output/` are generated local artifacts
and are ignored by Git. Do not copy them into tracked source or configuration.

## Validation protocol

1. **Freeze the question and counting contract.** Treat a crossing as a
   vehicle's visual center passing across the configured finite yellow line
   segment. Count each distinguishable vehicle at most once per direction
   within a burst, matching the current per-track counting behavior. Use
   negative-to-positive and positive-to-negative line-relative directions;
   do not infer compass headings. Record uncertain/occluded cases instead of
   guessing.
2. **Select an independent primary sample.** Before looking at any pipeline
   outputs, use a documented fixed random seed to choose bursts from both
   capture windows. Save the selected burst IDs and seed. Do not choose the
   primary sample based on reported count, traffic density, or visible
   detector output. After labels are frozen, check whether the sample includes
   zero-count cases. If needed, select extra zero-count or difficult cases as
   a separately reported challenge set; do not merge a result-selected
   challenge set into unbiased accuracy metrics.
3. **Create a blinded review packet.** Prepare frame sequences or short clips
   for both carriageways, showing the two preview lines but no detections,
   track IDs, candidate counts, or analysis files. Preserve original frame
   order and the five-frames-per-second timing.
4. **Annotate every crossing.** For each selected burst and each carriageway,
   record the number of crossings in both line-relative directions. When
   practical, note the frame interval and a vehicle description so duplicate
   counts can be identified. Mark uncertain crossings, occlusions, and
   truncated-at-burst-boundary vehicles explicitly.
5. **Adjudicate ambiguity.** Have a second review resolve uncertain events
   without seeing the model result. Keep unresolved events marked ambiguous;
   report them separately and do not silently include them as definite
   positives or negatives.
6. **Unblind and replay.** After the annotation file is frozen, run the exact
   current detector/tracker/finite-line code against the same frames. Record
   the model, tracker backend, line geometry, source burst, and code revision.
   Confirm `flow_rate_vph`, `flow_count_per_burst`, `line_crossings`, and the
   final per-frame crossing snapshot agree.
7. **Report both event and burst metrics.** Compare event-level precision,
   recall, and F1 using a predeclared frame-matching tolerance; also report
   per-direction exact burst-count agreement, mean absolute count error, and
   error by traffic level. Provide denominators and confidence intervals where
   sample size permits. Report the independent random sample separately from
   any challenge set.
8. **Agree on release gates before interpreting the results.** Ask the
   operator for acceptable precision/recall, count error, ambiguous-event
   rate, and minimum sample size before declaring pass/fail. The previously
   discussed 90% precision/recall and one-count-per-burst error are only
   example proposals, not established project requirements.

## Production progression after validation

If the independent sample meets the agreed gates, implement a general
multi-zone configuration behind a disabled-by-default feature flag. Keep
current single-ROI/single-line behavior as the fallback, reuse frame
detections across zones, and emit image-left/image-right counts and
camera-relative motion baselines as additive shadow outputs for camera 109
only. Do not expose physical speed units: current motion is pixels per sample
frame. Compare shadow results over an agreed monitoring period, then request
operator approval before enabling any production API/UI behavior or persisting
direction-specific calibration values.

If the gates fail or too many events are ambiguous, tune the line/ROI or
tracking behavior and repeat the blinded evaluation on a fresh held-out
sample. Do not tune against the primary test set and then report it as
independent validation.

## Constraints and safety checks

- Run Python tooling in Docker; host Python is not assumed available.
- Keep `config/camera_rois.json`, `config/camera_flow_lines.json`, and
  `config/camera_speed_calibration.json` unchanged during annotation and
  evaluation.
- Do not run new live capture, write labels, or start the validation task
  without the operator asking to proceed.
- Keep the existing pooled production path available until the camera-109
  shadow path has passed validation and been explicitly approved.
