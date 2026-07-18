"""FastAPI application entry point scaffold."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from trafficcam.api.routes import router
from trafficcam.web.map_page import render_map_page

app = FastAPI(title="Traffic Cam API")
app.include_router(router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Render the interactive congestion map."""
    return HTMLResponse(render_map_page())


@app.get("/health")
def health() -> dict:
    """Return a simple health response."""
    return {"status": "ok"}
