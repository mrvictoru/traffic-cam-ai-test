"""Minimal web app scaffold."""

from __future__ import annotations

import re
from html import escape

from trafficcam.api.routes import build_camera_summaries
from trafficcam.storage.json_store import JsonStore

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_DENSITY_COLORS = {
    "blocked": "#dc2626",
    "heavy": "#f97316",
    "moderate": "#facc15",
    "light": "#22c55e",
    "unknown": "#94a3b8",
}
for _color in _DENSITY_COLORS.values():
    if not _HEX_COLOR_RE.fullmatch(_color):
        raise ValueError(f"Invalid dashboard density color: {_color}")


def _density_color(density: str | None) -> str:
    return _DENSITY_COLORS.get((density or "unknown").lower(), _DENSITY_COLORS["unknown"])


def _hex_to_rgba(color: str, alpha: float) -> str:
    color = color.lstrip("#")
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _safe_percent(value: object, default: float = 50.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = default
    return max(0.0, min(100.0, round(numeric, 1)))


def _camera_title(camera: dict) -> str:
    return str(camera.get("name") or camera.get("camera_id") or "unknown")


def _camera_location(camera: dict) -> str:
    location_parts = [camera.get("district"), camera.get("sub_district")]
    formatted = " · ".join(str(part) for part in location_parts if part)
    return formatted or "Location pending"


def _camera_sort_key(camera: dict) -> tuple[int, str]:
    return (-camera.get("density_rank", 0), str(camera.get("camera_id") or ""))


def render_dashboard(store: JsonStore | None = None) -> str:
    """Render a first-pass dashboard with a map-style congestion overview."""
    if store is None:
        store = JsonStore("data")

    cameras = build_camera_summaries(store=store)
    if not cameras:
        return "<h1>Traffic Cam Dashboard</h1><p>No analyses available yet.</p>"

    total_cameras = len(cameras)
    approximate_count = sum(
        1 for camera in cameras if (camera.get("map_position") or {}).get("source") == "approximate"
    )
    blocked_count = sum(1 for camera in cameras if camera.get("latest_density") == "blocked")
    heavy_count = sum(1 for camera in cameras if camera.get("latest_density") == "heavy")
    approximate_label = "camera marker" if approximate_count == 1 else "camera markers"

    markers = []
    cards = []
    for camera in sorted(cameras, key=_camera_sort_key):
        density = str(camera.get("latest_density") or "unknown")
        color = _density_color(density)
        color_glow = _hex_to_rgba(color, 0.25)
        position = camera.get("map_position") or {}
        x_percent = _safe_percent(position.get("x_percent"))
        y_percent = _safe_percent(position.get("y_percent"))
        title = escape(_camera_title(camera))
        camera_id = escape(str(camera.get("camera_id") or "unknown"))
        location = escape(_camera_location(camera))
        captured_at = escape(str(camera.get("latest_captured_at") or "unknown"))
        flow_total = camera.get("latest_flow_total")
        flow_summary = f"{flow_total} vehicles / sample" if flow_total is not None else "Flow pending"
        position_source = escape(str(position.get("source") or "approximate"))

        markers.append(
            f"""
            <div class="map-marker" style="left:{x_percent}%; top:{y_percent}%; --marker-color:{color};">
              <span class="map-marker-dot" style="--marker-glow:{color_glow};"></span>
              <div class="map-marker-label">
                <strong>{title}</strong>
                <span>{camera_id}</span>
                <span>{escape(density.title())} congestion</span>
              </div>
            </div>
            """
        )
        cards.append(
            f"""
            <article class="camera-card" data-density="{escape(density)}">
              <header>
                <h3>{title}</h3>
                <span class="density-pill" style="--pill-color:{color};">{escape(density.title())}</span>
              </header>
              <p>Camera ID: {camera_id}</p>
              <p>{location}</p>
              <p>{escape(flow_summary)}</p>
              <p>Captured: {captured_at}</p>
              <p>Map placement: {position_source}</p>
            </article>
            """
        )

    return f"""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Traffic Cam Congestion Map</title>
    <style>
      :root {{
        color-scheme: dark;
        font-family: Arial, sans-serif;
      }}
      body {{
        margin: 0;
        background: #0f172a;
        color: #e2e8f0;
      }}
      .page {{
        display: grid;
        grid-template-columns: minmax(0, 2fr) minmax(320px, 1fr);
        gap: 24px;
        padding: 24px;
      }}
      .panel {{
        background: rgba(15, 23, 42, 0.9);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 20px;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.35);
      }}
      .hero {{
        padding: 24px;
      }}
      .stats {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
        margin-top: 20px;
      }}
      .stat {{
        background: rgba(30, 41, 59, 0.75);
        border-radius: 16px;
        padding: 16px;
      }}
      .stat strong {{
        display: block;
        font-size: 1.5rem;
        margin-bottom: 4px;
      }}
      .map-panel {{
        padding: 0 24px 24px;
      }}
      .map-surface {{
        position: relative;
        min-height: 560px;
        overflow: hidden;
        border-radius: 22px;
        background:
          radial-gradient(circle at 30% 28%, rgba(34, 197, 94, 0.26), transparent 20%),
          radial-gradient(circle at 58% 62%, rgba(234, 179, 8, 0.22), transparent 18%),
          radial-gradient(circle at 74% 34%, rgba(59, 130, 246, 0.15), transparent 22%),
          linear-gradient(180deg, #16324f 0%, #10253b 100%);
        border: 1px solid rgba(148, 163, 184, 0.22);
      }}
      .map-surface::before,
      .map-surface::after {{
        content: "";
        position: absolute;
        inset: 0;
      }}
      .map-surface::before {{
        background-image:
          linear-gradient(rgba(148, 163, 184, 0.12) 1px, transparent 1px),
          linear-gradient(90deg, rgba(148, 163, 184, 0.12) 1px, transparent 1px);
        background-size: 64px 64px;
      }}
      .map-surface::after {{
        background:
          radial-gradient(circle at 32% 32%, rgba(148, 163, 184, 0.17), transparent 18%),
          radial-gradient(circle at 62% 70%, rgba(148, 163, 184, 0.14), transparent 14%),
          radial-gradient(circle at 74% 38%, rgba(148, 163, 184, 0.14), transparent 12%);
      }}
      .map-overlay {{
        position: absolute;
        inset: 0;
        padding: 20px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }}
      .map-note,
      .map-legend {{
        align-self: flex-start;
        background: rgba(15, 23, 42, 0.82);
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-radius: 14px;
        padding: 12px 14px;
      }}
      .map-note {{
        max-width: 420px;
      }}
      .map-legend {{
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
      }}
      .legend-item {{
        display: inline-flex;
        gap: 8px;
        align-items: center;
        font-size: 0.92rem;
      }}
      .legend-swatch {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
      }}
      .map-marker {{
        position: absolute;
        transform: translate(-50%, -100%);
        z-index: 2;
      }}
      .map-marker-dot {{
        display: inline-block;
        width: 16px;
        height: 16px;
        border-radius: 999px;
        border: 3px solid rgba(15, 23, 42, 0.9);
        background: var(--marker-color);
        box-shadow: 0 0 0 8px var(--marker-glow);
      }}
      .map-marker-label {{
        margin-top: 8px;
        min-width: 130px;
        padding: 10px 12px;
        border-radius: 14px;
        background: rgba(15, 23, 42, 0.88);
        border: 1px solid rgba(148, 163, 184, 0.25);
      }}
      .map-marker-label strong,
      .camera-card h3 {{
        display: block;
        margin-bottom: 4px;
      }}
      .camera-list {{
        padding: 24px;
      }}
      .camera-grid {{
        display: grid;
        gap: 14px;
        margin-top: 18px;
      }}
      .camera-card {{
        padding: 16px;
        border-radius: 16px;
        background: rgba(30, 41, 59, 0.72);
        border: 1px solid rgba(148, 163, 184, 0.2);
      }}
      .camera-card header {{
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
      }}
      .camera-card p {{
        margin: 8px 0 0;
        color: #cbd5e1;
      }}
      .density-pill {{
        border-radius: 999px;
        padding: 6px 10px;
        font-size: 0.85rem;
        font-weight: 700;
        color: #0f172a;
        background: var(--pill-color);
      }}
      @media (max-width: 1080px) {{
        .page {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      <section class="panel">
        <div class="hero">
          <h1>Traffic Cam Congestion Map</h1>
          <p>A first-pass road congestion visualizer built from the latest persisted camera analyses.</p>
          <div class="stats">
            <div class="stat"><strong>{total_cameras}</strong><span>Active camera summaries</span></div>
            <div class="stat"><strong>{blocked_count}</strong><span>Blocked locations</span></div>
            <div class="stat"><strong>{heavy_count}</strong><span>Heavy congestion locations</span></div>
          </div>
        </div>
        <div class="map-panel">
          <div id="camera-map" class="map-surface">
            {''.join(markers)}
            <div class="map-overlay">
              <div class="map-note">
                {approximate_count} {approximate_label} currently use district-based approximate placement until camera coordinates are stored.
              </div>
              <div class="map-legend">
                <span class="legend-item"><span class="legend-swatch" style="background:{_DENSITY_COLORS['blocked']};"></span>Blocked</span>
                <span class="legend-item"><span class="legend-swatch" style="background:{_DENSITY_COLORS['heavy']};"></span>Heavy</span>
                <span class="legend-item"><span class="legend-swatch" style="background:{_DENSITY_COLORS['moderate']};"></span>Moderate</span>
                <span class="legend-item"><span class="legend-swatch" style="background:{_DENSITY_COLORS['light']};"></span>Light</span>
              </div>
            </div>
          </div>
        </div>
      </section>
      <aside class="panel camera-list">
        <h2>Camera congestion feed</h2>
        <div class="camera-grid">
          {''.join(cards)}
        </div>
      </aside>
    </main>
  </body>
</html>
"""
