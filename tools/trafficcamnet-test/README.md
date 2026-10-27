# TrafficCamNet camera 109 test

This isolated test runs NVIDIA's TrafficCamNet ONNX model from the DeepStream
7.1 container on the same 12 independently selected camera 109 bursts used by
the count audit. It does not change the YOLO runtime, production configuration,
or saved camera 109 geometry.

## Prerequisites

- Docker Desktop with GPU passthrough and an NVIDIA GPU.
- The existing ignored camera 109 captures under `output/`.
- The official `nvcr.io/nvidia/deepstream:7.1-triton-multiarch` image. The first
  run downloads this large NVIDIA image.

## Run

From PowerShell at the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\trafficcamnet-test\run.ps1
```

The execution-policy override applies only to this PowerShell process.

The script checks GPU access, prepares 12 short MP4s from the retained source
frames using the existing capture container's FFmpeg, then starts the separate
DeepStream container. A GStreamer pipeline runs the bundled TrafficCamNet ONNX
model through `nvinfer` and writes annotated MP4s. DeepStream builds a TensorRT
INT8 engine on first use; the engine is cached under the ignored test data so
later runs can reuse it.

Results are written to ignored local data:

- `data/trafficcamnet-test/results/videos/` — annotated MP4s.
- `data/trafficcamnet-test/results/logs/` — inference startup and pipeline logs.
- `data/trafficcamnet-test/models/` — generated TensorRT engine cache.

## Interpretation

This first pass tests that the NVIDIA detector can run on the actual source
frames and provides artifacts for visual comparison. It is not yet an
accuracy benchmark: the existing blind labels are incomplete and not
adjudicated ground truth. It saves annotated video, not structured detection
records or traffic counts. Do not change counting semantics or enable camera
109 production settings based on this run.

The supplied DeepStream sample model uses 960x544 detector input and the
NVIDIA sample's INT8 thresholds (0.4 for class 0 and 0.2 for the other
classes). The test keeps the 352x288 source dimensions at the stream muxer and
lets the model preprocessing resize frames, so box positions remain in source
image coordinates. The reference `deepstream-app` executable failed before
inference on this URI-source setup with `src_bin_muxer: Output width not set`;
the test therefore uses explicit GStreamer elements instead of that app
configuration wrapper.

To avoid rebuilding the TensorRT engine after changing DeepStream version,
GPU, or model precision, use a different engine-cache filename in
`config_infer_primary.txt`.
