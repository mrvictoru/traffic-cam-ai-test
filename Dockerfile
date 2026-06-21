FROM python:3.12-slim

WORKDIR /app

# Copy application files
COPY macau_dsat_feed.py .
COPY tests/ tests/

# Run tests to verify the image works
RUN python -m unittest discover -s tests -q

# Set entrypoint to the pipeline
ENTRYPOINT ["python", "macau_dsat_feed.py"]
CMD ["--pretty"]
