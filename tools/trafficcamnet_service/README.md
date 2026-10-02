# TrafficCamNet vision backend

The TrafficCamNet service runs NVIDIA DeepStream in a separate GPU container. The normal application image remains CPU-only and sends one ordered JPEG burst per camera analysis to the service on the private Compose network.

## Requirements and model files

- Docker Compose with NVIDIA GPU passthrough configured.
- The NVIDIA DeepStream 7.1 image and compatible driver/runtime. The service uses the existing `tools/trafficcamnet-test/config_infer_primary.txt` and `data/trafficcamnet-test/models/` cache.
- `data/trafficcamnet-test/models/trafficcamnet_ds71_b1_int8.engine` may be prebuilt by the TrafficCamNet test setup. If it is absent, DeepStream can build it from the ONNX model bundled in its image; the model-cache mount is writable so the engine can persist.

The first start can take longer while DeepStream initializes or builds the TensorRT engine. The service reports healthy only after a warmup frame has passed through `nvinfer`.

## Start with TrafficCamNet

From the repository root in PowerShell:

```powershell
docker compose -f docker-compose.yml -f docker-compose.trafficcamnet-service.yml up --build
```

The overlay selects `VISION_BACKEND=trafficcamnet` by default, waits for the sidecar health check, and does not publish the inference port to the host. Override `VISION_BACKEND` only when intentionally selecting another detector.

To manually roll back to YOLO, run the base Compose stack without the TrafficCamNet overlay:

```powershell
$env:VISION_BACKEND = "yolo"
docker compose -f docker-compose.yml up --build
```

The app uses its normal YOLO model/device settings. TrafficCamNet failures are reported for the affected camera; the application does not silently fall back to YOLO.

## API contract

- `GET /healthz` returns `200` only after model initialization; otherwise it returns `503`.
- `POST /v1/infer-burst` accepts `schema_version`, `camera_id`, and an ordered list of `{frame_index, jpeg_base64}` frames.
- The response includes the same `camera_id`, model/backend identity, and one ordered frame result per input, with vehicle detections in pixel coordinates.
- A burst has 1–30 JPEG frames, consistent dimensions, and configured encoded/decoded-size limits. The client and service reject invalid order, malformed images, size overruns, non-finite coordinates/confidence, and incomplete responses.
- Requests are serialized by the sidecar to prevent frame metadata from crossing between cameras. GStreamer and the loaded TensorRT model stay resident between requests.

## Validate

Run unit/API contract tests in the app image:

```powershell
docker compose -f docker-compose.yml build macau-feed
docker compose -f docker-compose.yml run --rm --no-deps --entrypoint python macau-feed -m pytest -q tests/unit/test_trafficcamnet_client.py tests/unit/test_trafficcamnet_service_api.py tests/integration/test_e2e_pipeline_script.py
```

Run the live HTTP smoke test after starting the combined stack:

```powershell
docker compose -f docker-compose.yml -f docker-compose.trafficcamnet-service.yml run --rm --no-deps -e RUN_TRAFFICCAMNET_INTEGRATION=1 --entrypoint python macau-feed -m pytest -q tests/integration/test_trafficcamnet_service.py
```

Inspect readiness and service errors with:

```powershell
docker compose -f docker-compose.yml -f docker-compose.trafficcamnet-service.yml ps
docker compose -f docker-compose.yml -f docker-compose.trafficcamnet-service.yml logs trafficcamnet-vision
```
