#!/usr/bin/env bash
set -euo pipefail

mkdir -p /work/results/videos /work/results/logs /work/models
nvidia-smi
base=/opt/nvidia/deepstream/deepstream-7.1/samples
model_dir="${base}/models/Primary_Detector"
limit="${TRAFFICCAMNET_LIMIT:-0}"
completed=0

for input in /work/videos/*.mp4; do
    name="$(basename "$input" .mp4)"
    output="/work/results/videos/${name}_trafficcamnet.mp4"
    log="/work/results/logs/${name}.log"
    printf 'Running TrafficCamNet on %s\n' "$name"
    set +e
    gst-launch-1.0 -e \
        filesrc location="$input" ! \
        qtdemux ! h264parse ! nvv4l2decoder ! queue ! mux.sink_0 \
        nvstreammux name=mux batch-size=1 width=352 height=288 live-source=0 batched-push-timeout=40000 ! \
        nvinfer config-file-path=/test/config_infer_primary.txt batch-size=1 ! \
        nvdsosd ! nvv4l2h264enc bitrate=2000000 ! h264parse ! qtmux ! \
        filesink location="$output" 2>&1 | tee "$log"
    status="${PIPESTATUS[0]}"
    set -e
    if [ "$status" -ne 0 ]; then
        printf 'TrafficCamNet failed for %s (exit %s); see %s\n' "$name" "$status" "$log" >&2
        exit "$status"
    fi
    engine="${model_dir}/resnet18_trafficcamnet_pruned.onnx_b1_gpu0_int8.engine"
    if [[ -f "$engine" && ! -f /work/models/trafficcamnet_ds71_b1_int8.engine ]]; then
        cp "$engine" /work/models/trafficcamnet_ds71_b1_int8.engine
    fi
    completed=$((completed + 1))
    if [ "$limit" -gt 0 ] && [ "$completed" -ge "$limit" ]; then
        break
    fi
done

printf 'TrafficCamNet processed %s clip(s); results written under /work/results\n' "$completed"
