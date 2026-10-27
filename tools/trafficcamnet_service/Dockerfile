FROM nvcr.io/nvidia/deepstream:7.1-triton-multiarch

RUN apt-get update && apt-get install -y --no-install-recommends python3-gi python3-gst-1.0 python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --break-system-packages \
    https://github.com/NVIDIA-AI-IOT/deepstream_python_apps/releases/download/v1.1.11/pyds-1.1.11-py3-none-linux_x86_64.whl \
    fastapi uvicorn Pillow

WORKDIR /service
COPY tools/trafficcamnet_service/ /service/trafficcamnet_service/
COPY tools/trafficcamnet-test/config_infer_primary.txt /test/config_infer_primary.txt

ENV TRAFFICCAMNET_CONFIG_PATH=/test/config_infer_primary.txt
ENV TRAFFICCAMNET_INFERENCE_TIMEOUT_SECONDS=15
ENV TRAFFICCAMNET_MAX_FRAMES=30
ENV TRAFFICCAMNET_MAX_BURST_BYTES=16777216

EXPOSE 8080
ENTRYPOINT ["python3", "-m", "uvicorn", "trafficcamnet_service.app:app", "--host", "0.0.0.0", "--port", "8080"]
