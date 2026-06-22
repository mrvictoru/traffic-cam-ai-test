FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest fastapi

# Copy application files
COPY macau_dsat_feed.py ./
COPY src/ ./src/
COPY tests/ ./tests/
COPY pytest.ini ./pytest.ini

ENV PYTHONPATH=/app/src

# Set entrypoint to the new package CLI
ENTRYPOINT ["python", "-m", "trafficcam.cli"]
CMD ["--mode", "discover"]
