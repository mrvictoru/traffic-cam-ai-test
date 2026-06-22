FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY macau_dsat_feed.py .
COPY tests/ tests/

# Set entrypoint to the pipeline
ENTRYPOINT ["python", "macau_dsat_feed.py"]
CMD ["--pretty"]
