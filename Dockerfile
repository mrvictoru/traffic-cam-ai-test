FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    pytest fastapi \
    transformers \
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
ENV HF_HOME=/app/.cache/huggingface

# Set entrypoint to the new package CLI
ENTRYPOINT ["python", "-m", "trafficcam.cli"]
CMD ["--mode", "discover"]
