# Matched detector comparison

This isolated workflow captures live DSAT streams, runs the production YOLO detector and NVIDIA TrafficCamNet on the same clips, then replays both saved detection sets through the existing burst-analysis pipeline. It does not update production analysis history. Run commands from the repository root in PowerShell; Python and FFmpeg are provided by Docker.

## Run

```powershell
$runDir = Join-Path (Get-Location).Path 'data\model-comparison-YYYYMMDD-HHMM'
$env:MODEL_COMPARISON_HOST_DIR = $runDir

docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison build trafficcamnet-comparison yolo-comparison
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps --entrypoint python yolo-comparison /compare/capture.py --output-dir /data --rounds 3 --interval-seconds 300 --duration-seconds 120 --fps 5
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps yolo-comparison --run-dir /data --duration-seconds 30
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps yolo-comparison --run-dir /data --duration-seconds 120
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps trafficcamnet-comparison --run-dir /data --duration-seconds 30
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps trafficcamnet-comparison --run-dir /data --duration-seconds 120
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps --entrypoint python yolo-comparison /compare/replay_analysis.py --run-dir /data --duration-seconds 30 --backend both
docker compose -f docker-compose.trafficcamnet.yml --profile model-comparison run --rm --no-deps --entrypoint python yolo-comparison /compare/replay_analysis.py --run-dir /data --duration-seconds 120 --backend both
```

Both inference scripts support `--camera-id` and `--round` to limit a smoke test. `capture.py` discovers the configured four cameras (49, 51, 58, 109) and writes per-capture metadata to `capture-manifest.json`; stream URLs are deliberately omitted.

## Output and metric definitions

- `round-*/cam-*-120s.mp4`: H.264 source clips, captured concurrently at 5 FPS.
- `frames/round-*/cam-*/frame_*.jpg`: common OpenCV-decoded JPEG frames written during YOLO inference; both model results are replayed against these same ordered images.
- `detections/{yolo,trafficcamnet}/round-*/cam-*-{30,120}s.json`: per-frame detections and model timing.
- `analysis/{yolo,trafficcamnet}/round-*/cam-*-{30,120}s.json`: shared-pipeline analysis without production persistence.
- YOLO per-call latency includes `detector.analyze`; its first call includes lazy model initialization. Its wall time includes video decode, JPEG writing, and all detector calls.
- TrafficCamNet `nvinfer_stage` measures elapsed wall time between the `nvinfer` sink and source pad probes; this is not an isolated CUDA-kernel measurement. Its total wall time includes video decode. First-detection delay includes startup/model initialization.
- Both GPU-memory values are periodic `nvidia-smi` device-wide samples, not per-process VRAM attribution.
- TrafficCamNet class thresholds are configured in `tools/trafficcamnet-test/config_infer_primary.txt` (0.4 for class 0; 0.2 for other classes); YOLO uses the project-wide confidence threshold (default 0.3). These thresholds are not equivalent.
- The recorded congestion and flow comparisons are pipeline-output comparisons, not accuracy scores. A manually adjudicated, matched ground-truth set is required to estimate detection/count accuracy.

The `model-comparison` Compose profile is opt-in; it does not replace or modify the normal application detector configuration.
