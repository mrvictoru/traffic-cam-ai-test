# Camera 109 independent count audit (2026-09-28)

## Decision

**Do not enable image-left/image-right production counting or persist camera
109 speed calibration yet.** A blind, outcome-independent sample and a fresh
offline replay are available, but they do not establish count accuracy: the
352×288 frames have unresolved center-line crossings and the independent
visual first pass is neither exhaustive nor human-adjudicated. There are no
defensible event precision/recall or per-burst count-error estimates.

## Frozen sample and inputs

The frozen selection recipe, preview-only geometry, and predeclared
two-frame event-matching tolerance are recorded in
`data/camera109-independent-validation/sample-selection.json` (ignored local
data). Six bursts from each of the two 2026-09-27 afternoon capture windows
were selected before opening pipeline count results:

| Capture window | Sampled burst IDs |
|---|---|
| 15:07–15:12 Asia/Macau | 03, 05, 06, 09, 13, 15 |
| 15:54–16:00 Asia/Macau | 02, 11, 12, 17, 18, 20 |

The selection excluded bursts 01 and 07, previously examined because of
pipeline-selected events. Sampling used .NET `System.Random(1090927)` without
replacement over the remaining IDs independently of reported counts. All 12
bursts were complete (30 retained frames at 5 FPS each), or 360 source frames
and 720 zone-frame analyses. The original, line-only sheets are in
`data/camera109-independent-validation/blinded-packet/`. The packet contains
no tracker ID, bounding box, or prediction. Yellow is image-left; cyan is
image-right. These names are image-relative, not geographic.

## Blind visual pass and replay

The first AI visual pass was recorded *before* reading replay counts, in
`data/camera109-independent-validation/blind-first-pass.json`. It is a
review aid, **not ground truth**. First-window counts could not be exhaustively
resolved from the overview sheets; a separate blind reviewer of the second
window marked three apparent crossings definite but could not certify
exhaustiveness or zero-count cases. Ambiguous two-wheelers, endpoint touches,
occlusions, and crowded scenes remain unresolved. No zero label was inferred
from an absence of confidently visible crossings.

The saved preview analysis records were audited for exact source-frame match.
Then revision `a060ad0` replayed all 24 selected zone-bursts using YOLO11s and
the simple tracker against the retained originals. The fresh counts **and
per-frame crossing timestamps matched the saved preview in 24/24
zone-bursts**. In all 24, `flow_rate_vph`, `flow_count_per_burst`,
`line_crossings`, and the last per-frame snapshot agree. This verifies output
consistency and reproducibility on this sample, **not vehicle-count accuracy**.

| Zone | Zone-bursts | Pipeline crossings | Pipeline zero-count bursts |
|---|---:|---:|---:|
| Image-left | 12 | 19 | 1 |
| Image-right | 12 | 14 | 4 |

These are **pipeline outputs**, not human counts. Fresh inference over 720
zone-frames took about 94 seconds of analysis-loop time in one cached-model
Docker invocation; that is an exploratory local runtime, not a production
latency benchmark.

Of the three provisional definite visual events in the second-window first
pass, two had a pipeline event within the predeclared ±2-frame tolerance.
For second-window burst 02 image-left, the visual reviewer located a
silver/white car's center crossing around frames 09–12 while the pipeline
reported its event at frame 05. That discrepancy persists on fresh replay.
Second-window burst 11 image-right produced two pipeline increments in
frame 06, but the reviewer could not independently verify two distinct
centers crossing the finite cyan segment. Neither observation alone proves
an ID switch or a wrong count; both require targeted frame-level
adjudication. The complete per-burst comparison is in
`data/camera109-independent-validation/replay-audit.json` and the fresh
offline run in `data/camera109-independent-validation/replay-current.json`.

## Remaining release gate

1. Have an independent human reviewer annotate **all** selected bursts
   frame-by-frame, both zones, noting each vehicle identity, visual-center
   crossing interval, direction, and uncertain/occluded/endpoint cases.
   Adjudicate uncertain events with a second reviewer before revealing
   predictions. Preserve the frozen sample and don't tune lines or tracker
   against it.
2. Agree with the operator *before declaring pass/fail* on the minimum
   annotation sample, event precision and recall, exact burst-count agreement,
   mean absolute count error, ambiguous-event handling, and monitoring
   period. No threshold is assumed by this audit.
3. Compute event and burst metrics on adjudicated labels, report denominator
   and uncertainty, and include true zero-crossing bursts. If the sample is
   too small or too ambiguous, label additional randomly selected held-out
   bursts separately. Evaluate any tuned geometry on a **new** holdout.
4. Only after those gates pass, implement disabled-by-default multi-zone
   camera 109 shadow counts and camera-relative motion baselines as described
   in [the validation guide](./camera109-count-validation-guide.md). Obtain
   explicit approval before production/API changes or baseline persistence.

No live capture, production geometry, or camera 109 calibration was changed
by this audit.
