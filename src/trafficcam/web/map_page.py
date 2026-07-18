"""Leaflet-based interactive congestion map page.

Renders a self-contained HTML page (inline CSS + JS) that loads camera
summaries from the FastAPI endpoints and plots them on an OpenStreetMap
basemap. Leaflet is pulled from a CDN so no frontend build step is required.
"""

from __future__ import annotations

import json

from trafficcam.api.routes import build_camera_summaries
from trafficcam.storage.json_store import JsonStore

_DENSITY_COLORS = {
    "blocked": "#dc2626",
    "heavy": "#f97316",
    "moderate": "#facc15",
    "light": "#22c55e",
    "unknown": "#94a3b8",
}


def _cameras_payload(store: JsonStore | None) -> str:
    """Serialize camera summaries as a JSON string safe to embed in a script."""
    if store is None:
        store = JsonStore("data")
    summaries = build_camera_summaries(store=store)
    return json.dumps(summaries, ensure_ascii=False)


def render_map_page(store: JsonStore | None = None) -> str:
    """Render the interactive map page with an initial camera payload."""
    cameras_json = _cameras_payload(store)
    colors_json = json.dumps(_DENSITY_COLORS)
    return _PAGE_TEMPLATE.replace("__CAMERAS_JSON__", cameras_json).replace(
        "__DENSITY_COLORS__", colors_json
    )


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Macau Traffic Congestion Map</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; background: #0f172a; color: #e2e8f0; }
    #app { position: relative; height: 100vh; width: 100vw; }
    #map { position: absolute; inset: 0; }
    .hud { position: absolute; z-index: 1000; }
    #title-card {
      top: 12px; left: 56px; background: rgba(15,23,42,0.9); border: 1px solid rgba(148,163,184,0.3);
      border-radius: 12px; padding: 10px 14px; max-width: 320px; backdrop-filter: blur(4px);
    }
    #title-card h1 { font-size: 1rem; margin: 0 0 2px; }
    #title-card p { font-size: 0.78rem; margin: 0; color: #94a3b8; }
    #toolbar { top: 12px; right: 12px; display: flex; gap: 8px; align-items: center; }
    .btn {
      background: rgba(15,23,42,0.9); color: #e2e8f0; border: 1px solid rgba(148,163,184,0.4);
      border-radius: 10px; padding: 8px 12px; font-size: 0.82rem; cursor: pointer;
    }
    .btn:hover { background: rgba(30,41,59,0.95); }
    #status { font-size: 0.72rem; color: #94a3b8; background: rgba(15,23,42,0.8); padding: 6px 10px; border-radius: 8px; }
    #legend {
      bottom: 20px; left: 12px; background: rgba(15,23,42,0.9); border: 1px solid rgba(148,163,184,0.3);
      border-radius: 12px; padding: 10px 12px; font-size: 0.78rem;
    }
    #legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
    .swatch { width: 12px; height: 12px; border-radius: 50%; border: 2px solid rgba(15,23,42,0.8); }
    .cam-marker {
      width: 18px; height: 18px; border-radius: 50%; border: 3px solid rgba(15,23,42,0.9);
      box-shadow: 0 0 0 6px rgba(0,0,0,0.15); cursor: pointer;
    }
    #detail-panel {
      top: 0; right: 0; height: 100%; width: 360px; background: rgba(15,23,42,0.97);
      border-left: 1px solid rgba(148,163,184,0.25); padding: 18px; overflow-y: auto;
      transform: translateX(100%); transition: transform 0.25s ease; z-index: 1100;
    }
    #detail-panel.open { transform: translateX(0); }
    #detail-panel .close { position: absolute; top: 10px; right: 12px; background: none; border: none; color: #94a3b8; font-size: 1.3rem; cursor: pointer; }
    #detail-panel h2 { font-size: 1.05rem; margin: 0 24px 4px 0; }
    #detail-panel .sub { color: #94a3b8; font-size: 0.8rem; margin: 0 0 12px; }
    .density-badge { display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; color: #0f172a; }
    .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 14px 0; }
    .stat { background: rgba(30,41,59,0.7); border-radius: 10px; padding: 10px; }
    .stat .k { font-size: 0.68rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; }
    .stat .v { font-size: 1.05rem; font-weight: 600; margin-top: 2px; }
    .section { margin-top: 16px; }
    .section h3 { font-size: 0.82rem; margin: 0 0 8px; color: #cbd5e1; border-bottom: 1px solid rgba(148,163,184,0.2); padding-bottom: 5px; }
    .flowbar { display: flex; height: 16px; border-radius: 8px; overflow: hidden; font-size: 0.62rem; font-weight: 700; }
    .flowbar div { display: flex; align-items: center; justify-content: center; color: #0f172a; }
    .nb { background: #38bdf8; } .sb { background: #f472b6; }
    #spark { width: 100%; height: 60px; }
    .frame-item { font-size: 0.76rem; color: #cbd5e1; padding: 6px 8px; background: rgba(30,41,59,0.5); border-radius: 8px; margin: 4px 0; }
    .stream-link { font-size: 0.76rem; color: #38bdf8; word-break: break-all; }
    .muted { color: #64748b; font-size: 0.78rem; }
    @media (max-width: 720px) { #detail-panel { width: 100%; } #title-card { max-width: 200px; } }
  </style>
</head>
<body>
<div id="app">
  <div id="map"></div>
  <div id="title-card" class="hud">
    <h1>Macau Traffic Congestion</h1>
    <p>Live camera congestion. Click a marker for detail.</p>
  </div>
  <div id="toolbar" class="hud">
    <span id="status">Loading…</span>
    <button class="btn" id="refresh-btn" title="Refresh now">⟳ Refresh</button>
    <label class="btn" style="display:flex;gap:6px;align-items:center;cursor:pointer;">
      <input type="checkbox" id="auto-refresh" checked style="margin:0;"> Auto
    </label>
  </div>
  <div id="legend" class="hud"></div>
  <aside id="detail-panel" class="hud">
    <button class="close" id="close-panel">&times;</button>
    <div id="detail-content"><p class="muted">Select a camera marker to see details.</p></div>
  </aside>
</div>
<script>
const DENSITY_COLORS = __DENSITY_COLORS__;
const INITIAL_CAMERAS = __CAMERAS_JSON__;
const REFRESH_MS = 30000;

const map = L.map('map', { zoomControl: true }).setView([22.169, 113.555], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = [];
let refreshTimer = null;

function densityColor(d) { return DENSITY_COLORS[(d || 'unknown').toLowerCase()] || DENSITY_COLORS.unknown; }

function buildLegend() {
  const el = document.getElementById('legend');
  el.innerHTML = '<strong style="font-size:0.8rem;">Congestion</strong>' + Object.entries(DENSITY_COLORS)
    .filter(([k]) => k !== 'unknown')
    .map(([k, c]) => `<div class="row"><span class="swatch" style="background:${c}"></span>${k[0].toUpperCase() + k.slice(1)}</div>`)
    .join('');
}

function clearMarkers() { markers.forEach(m => map.removeLayer(m)); markers = []; }

function directionArrow(cam) {
  const split = cam.latest_flow_split;
  if (!split) return '';
  const nb = split.northbound || 0, sb = split.southbound || 0, total = nb + sb;
  if (!total) return '';
  const dominant = nb >= sb ? '▲ NB' : '▼ SB';
  return `<div style="font-size:0.66rem;font-weight:700;color:#0f172a;background:#e2e8f0;border-radius:6px;padding:1px 5px;margin-top:3px;text-align:center;">${dominant}</div>`;
}

function addMarkers(cameras) {
  clearMarkers();
  cameras.forEach(cam => {
    const pos = cam.map_position || {};
    const lat = cam.latitude != null ? cam.latitude : pos.latitude;
    const lon = cam.longitude != null ? cam.longitude : pos.longitude;
    if (lat == null || lon == null) return;
    const color = densityColor(cam.latest_density);
    const icon = L.divIcon({
      className: '',
      html: `<div><div class="cam-marker" style="background:${color}"></div>${directionArrow(cam)}</div>`,
      iconSize: [40, 34], iconAnchor: [20, 14]
    });
    const marker = L.marker([lat, lon], { icon }).addTo(map);
    marker.on('click', () => openDetail(cam.camera_id, cam));
    markers.push(marker);
  });
}

function sparkline(history) {
  const order = { unknown: 0, light: 1, moderate: 2, heavy: 3, blocked: 4 };
  const pts = history.map(h => order[(h.density || 'unknown').toLowerCase()] || 0);
  if (pts.length < 2) return '<p class="muted">Not enough history.</p>';
  const w = 320, h = 60, pad = 6;
  const step = (w - pad * 2) / (pts.length - 1);
  const y = v => h - pad - (v / 4) * (h - pad * 2);
  const path = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${(pad + i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
  const dots = pts.map((v, i) => `<circle cx="${(pad + i * step).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5" fill="#38bdf8"/>`).join('');
  return `<svg id="spark" viewBox="0 0 ${w} ${h}"><path d="${path}" fill="none" stroke="#38bdf8" stroke-width="2"/>${dots}</svg>`;
}

async function openDetail(id, cam) {
  const panel = document.getElementById('detail-panel');
  const content = document.getElementById('detail-content');
  panel.classList.add('open');
  content.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const [detail, history] = await Promise.all([
      fetch(`/api/cameras/${encodeURIComponent(id)}`).then(r => r.json()),
      fetch(`/api/cameras/${encodeURIComponent(id)}/history?limit=12`).then(r => r.ok ? r.json() : [])
    ]);
    const color = densityColor(detail.density);
    const split = detail.flow_rate_vph || {};
    const nb = split.northbound || 0, sb = split.southbound || 0, tot = nb + sb;
    const nbW = tot ? Math.round(nb / tot * 100) : 50;
    content.innerHTML = `
      <h2>${detail.name || 'Camera ' + detail.camera_id}</h2>
      <p class="sub">ID ${detail.camera_id} · ${[detail.district, detail.sub_district].filter(Boolean).join(' · ') || 'Location pending'}</p>
      <span class="density-badge" style="background:${color}">${(detail.density || 'unknown').toUpperCase()}</span>
      <div class="stat-grid">
        <div class="stat"><div class="k">Vehicles</div><div class="v">${detail.vehicle_count ?? '—'}</div></div>
        <div class="stat"><div class="k">Active tracks</div><div class="v">${detail.active_tracks ?? '—'}</div></div>
        <div class="stat"><div class="k">Confidence</div><div class="v">${detail.mean_confidence != null ? (detail.mean_confidence * 100).toFixed(1) + '%' : '—'}</div></div>
        <div class="stat"><div class="k">Scene</div><div class="v">${detail.scene || '—'}</div></div>
      </div>
      <div class="section"><h3>Directional flow (vph)</h3>
        ${tot ? `<div class="flowbar"><div class="nb" style="width:${nbW}%">NB ${nb}</div><div class="sb" style="width:${100 - nbW}%">SB ${sb}</div></div>` : '<p class="muted">No flow data.</p>'}
      </div>
      <div class="section"><h3>Density trend</h3>${Array.isArray(history) ? sparkline(history) : '<p class="muted">No history.</p>'}</div>
      <div class="section"><h3>Frames (${(detail.per_frame || []).length})</h3>
        ${(detail.per_frame || []).map(f => `<div class="frame-item">#${f.frame_idx}: ${f.vehicle_count} vehicles · ${f.density || '—'}</div>`).join('') || '<p class="muted">No frames.</p>'}
      </div>
      <div class="section"><h3>Captured</h3><p class="muted">${detail.captured_at || 'unknown'}</p></div>
      ${detail.stream_url ? `<div class="section"><h3>Stream</h3><span class="stream-link">${detail.stream_url}</span></div>` : ''}
    `;
  } catch (e) {
    content.innerHTML = `<p class="muted">Failed to load detail for camera ${id}.</p>`;
  }
}

async function refresh() {
  const status = document.getElementById('status');
  try {
    const res = await fetch('/api/cameras');
    const cameras = await res.json();
    addMarkers(cameras);
    status.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (e) {
    status.textContent = 'Refresh failed';
  }
}

function setupAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => { if (document.getElementById('auto-refresh').checked) refresh(); }, REFRESH_MS);
}

document.getElementById('refresh-btn').addEventListener('click', refresh);
document.getElementById('close-panel').addEventListener('click', () => document.getElementById('detail-panel').classList.remove('open'));
document.getElementById('auto-refresh').addEventListener('change', setupAutoRefresh);

buildLegend();
addMarkers(INITIAL_CAMERAS);
document.getElementById('status').textContent = 'Loaded ' + INITIAL_CAMERAS.length + ' cameras';
setupAutoRefresh();
</script>
</body>
</html>
"""
