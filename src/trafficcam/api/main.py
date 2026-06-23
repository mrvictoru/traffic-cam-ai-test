"""FastAPI application entry point scaffold."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Traffic Cam API")


@app.get("/health")
def health() -> dict:
    """Return a simple health response."""
    return {"status": "ok"}
