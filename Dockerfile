FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    pytest fastapi \
    transformers \
    ultralytics \
    torch torchvision \
    opencv-python-headless \
    numpy \
    Pillow

# Copy application files
COPY macau_dsat_feed.py ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/
COPY pytest.ini ./pytest.ini

ENV PYTHONPATH=/app/src
ENV MODEL_CACHE_DIR=/app/model-cache
ENV HF_HOME=/app/model-cache/huggingface
ENV TRANSFORMERS_CACHE=/app/model-cache/huggingface
ENV ULTRALYTICS_HOME=/app/model-cache/ultralytics
ENV YOLO_CONFIG_DIR=/app/model-cache/ultralytics/config

# Set entrypoint to the new package CLI
ENTRYPOINT ["python", "-m", "trafficcam.cli"]
CMD ["--mode", "discover"]
