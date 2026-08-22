"""Dashboard + interactive congestion map page.

Renders a self-contained HTML page (inline CSS + JS) with:
- overview header cards (avg score, heavy/blocked counts, cameras online)
- searchable/sortable camera list
- Leaflet map with congestion-coloured markers + inline score pills
- per-camera detail panel with continuous score chart

Leaflet is loaded from a CDN; no frontend build step required.
"""

from __future__ import annotations

import json

from trafficcam.api.routes import build_camera_summaries, get_overview
from trafficcam.storage.json_store import JsonStore

_DENSITY_COLORS = {
    "blocked": "#dc2626",
    "heavy": "#f97316",
    "moderate": "#facc15",
    "light": "#22c55e",
    "unknown": "#94a3b8",
}


def _payload(store: JsonStore | None) -> str:
    """Serialize initial cameras + overview payloads for embedding."""
    if store is None:
        store = JsonStore("data")
    summaries = build_camera_summaries(store=store)
    try:
        overview = get_overview(store=store)
    except Exception:
        overview = {}
    return json.dumps({"cameras": summaries, "overview": overview}, ensure_ascii=False)


def render_map_page(store: JsonStore | None = None) -> str:
    """Render the dashboard page with an initial payload."""
    payload_json = _payload(store)
    colors_json = json.dumps(_DENSITY_COLORS)
    return _PAGE_TEMPLATE.replace("__PAYLOAD_JSON__", payload_json).replace(
        "__DENSITY_COLORS__", colors_json
    )


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Macau Traffic Congestion Dashboard</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
    integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
    integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
  <style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; background: #0f172a; color: #e2e8f0; }
    #app { display: flex; flex-direction: column; height: 100vh; width: 100vw; }
    header {
      display: flex; align-items: center; gap: 14px; padding: 10px 16px;
      background: rgba(15,23,42,0.95); border-bottom: 1px solid rgba(148,163,184,0.25);
      flex-wrap: wrap; z-index: 1200;
    }
    header h1 { font-size: 1.05rem; margin: 0; white-space: nowrap; }
    .cards { display: flex; gap: 10px; flex-wrap: wrap; flex: 1; }
    .card {
      background: rgba(30,41,59,0.7); border-radius: 10px; padding: 6px 12px;
      min-width: 92px; text-align: center;
    }
    .card .k { font-size: 0.62rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
    .card .v { font-size: 1.12rem; font-weight: 700; margin-top: 2px; }
    #toolbar { display: flex; gap: 8px; align-items: center; }
    #status { font-size: 0.7rem; color: #94a3b8; background: rgba(2,6,23,0.5); padding: 5px 9px; border-radius: 8px; }
    .btn {
      background: rgba(30,41,59,0.9); color: #e2e8f0; border: 1px solid rgba(148,163,184,0.4);
      border-radius: 8px; padding: 7px 11px; font-size: 0.78rem; cursor: pointer;
    }
    .btn:hover { background: rgba(51,65,85,0.95); }
    main { flex: 1; display: flex; min-height: 0; position: relative; z-index: 500; }
    #sidebar {
      width: 340px; overflow-y: auto; padding: 10px;
      border-right: 1px solid rgba(148,163,184,0.25); background: rgba(2,6,23,0.55);
      display: flex; flex-direction: column; gap: 8px;
    }
    #search {
      background: rgba(30,41,59,0.8); color: #e2e8f0; border: 1px solid rgba(148,163,184,0.35);
      border-radius: 8px; padding: 8px 10px; font-size: 0.82rem; outline: none;
    }
    #camera-list { display: flex; flex-direction: column; gap: 6px; }
    .cam-row {
      display: grid; grid-template-columns: auto 1fr auto; gap: 10px; align-items: center;
      background: rgba(30,41,59,0.6); border: 1px solid transparent; border-radius: 10px;
      padding: 8px 10px; cursor: pointer;
    }
    .cam-row:hover { background: rgba(51,65,85,0.7); border-color: rgba(56,189,248,0.4); }
    .dot { width: 13px; height: 13px; border-radius: 50%; border: 2px solid rgba(15,23,42,0.9); }
    .cam-row .name { font-size: 0.82rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .cam-row .sub { font-size: 0.68rem; color: #94a3b8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .score-pill { font-size: 0.72rem; font-weight: 700; border-radius: 999px; padding: 2px 8px; color: #0f172a; }
    #map-wrap { position: relative; flex: 1; min-width: 0; }
    #map { position: absolute; inset: 0; }
    #legend {
      position: absolute; bottom: 18px; left: 12px; z-index: 1000;
      background: rgba(15,23,42,0.9); border: 1px solid rgba(148,163,184,0.3);
      border-radius: 12px; padding: 9px 12px; font-size: 0.75rem;
    }
    #legend .row { display: flex; align-items: center; gap: 8px; margin: 3px 0; }
    #legend .swatch { width: 11px; height: 11px; border-radius: 50%; border: 2px solid rgba(15,23,42,0.8); }
    .stale-badge {
      font-size: 0.62rem; color: #fca5a5; background: rgba(220,38,38,0.15);
      border: 1px solid rgba(220,38,38,0.4); border-radius: 6px; padding: 1px 6px; margin-left: 6px;
    }
    #detail-panel {
      top: 0; right: 0; height: 100%; width: 380px; background: rgba(15,23,42,0.98);
      border-left: 1px solid rgba(148,163,184,0.25); padding: 18px; overflow-y: auto;
      transform: translateX(100%); transition: transform 0.25s ease; z-index: 1300; position: fixed;
    }
    #detail-panel.open { transform: translateX(0); }
    #detail-panel .close { position: absolute; top: 10px; right: 12px; background: none; border: none; color: #94a3b8; font-size: 1.3rem; cursor: pointer; }
    #detail-panel h2 { font-size: 1.02rem; margin: 0 26px 4px 0; }
    #detail-panel .sub { color: #94a3b8; font-size: 0.76rem; margin: 0 0 12px; }
    .density-badge { display: inline-block; padding: 4px 12px; border-radius: 999px; font-weight: 700; font-size: 0.78rem; color: #0f172a; }
    .stat-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 14px 0; }
    .stat { background: rgba(30,41,59,0.7); border-radius: 10px; padding: 9px; }
    .stat .k { font-size: 0.62rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em; }
    .stat .v { font-size: 1rem; font-weight: 600; margin-top: 2px; }
    .section { margin-top: 15px; }
    .section h3 { font-size: 0.8rem; margin: 0 0 8px; color: #cbd5e1; border-bottom: 1px solid rgba(148,163,184,0.2); padding-bottom: 5px; }
    .frame-preview { width: 100%; display: block; border-radius: 12px; border: 1px solid rgba(148,163,184,0.25); background: rgba(2,6,23,0.85); }
    #chart { width: 100%; height: 90px; }
    .flowbar { display: flex; height: 16px; border-radius: 8px; overflow: hidden; font-size: 0.62rem; font-weight: 700; }
    .flowbar div { display: flex; align-items: center; justify-content: center; color: #0f172a; }
    .nb { background: #38bdf8; } .sb { background: #f472b6; }
    .stream-link { font-size: 0.74rem; color: #38bdf8; word-break: break-all; }
    .muted { color: #64748b; font-size: 0.76rem; }
    @media (max-width: 900px) {
      #sidebar { display: none; }
      #detail-panel { width: 100%; }
    }
  </style>
</head>
<body>
<div id="app">
  <header>
    <h1>Macau Traffic</h1>
    <div class="cards" id="cards"></div>
    <div id="toolbar">
      <span id="status">Loading…</span>
      <button class="btn" id="refresh-btn">⟳ Refresh</button>
      <label class="btn" style="display:flex;gap:6px;align-items:center;cursor:pointer;">
        <input type="checkbox" id="auto-refresh" checked style="margin:0;"> Auto
      </label>
    </div>
  </header>
  <main>
    <aside id="sidebar">
      <input id="search" type="text" placeholder="Search camera or district…">
      <div id="camera-list"></div>
    </aside>
    <div id="map-wrap">
      <div id="map"></div>
      <div id="legend" class="hud"></div>
    </div>
  </main>
  <aside id="detail-panel" class="hud">
    <button class="close" id="close-panel">&times;</button>
    <div id="detail-content"><p class="muted">Select a camera to see details.</p></div>
  </aside>
</div>
<script>
const DENSITY_COLORS = __DENSITY_COLORS__;
const INITIAL = __PAYLOAD_JSON__;
const REFRESH_MS = 15000;
const DENSITY_ORDER = { blocked: 4, heavy: 3, moderate: 2, light: 1, unknown: 0 };

let CAMERAS = INITIAL.cameras || [];
const map = L.map('map', { zoomControl: true }).setView([22.169, 113.555], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = [];
let refreshTimer = null;

function densityColor(d) { return DENSITY_COLORS[(d || 'unknown').toLowerCase()] || DENSITY_COLORS.unknown; }
function scoreColor(score) {
  if (score == null) return DENSITY_COLORS.unknown;
  if (score >= 75) return DENSITY_COLORS.blocked;
  if (score >= 50) return DENSITY_COLORS.heavy;
  if (score >= 25) return DENSITY_COLORS.moderate;
  return DENSITY_COLORS.light;
}
function minutesAgo(iso) {
  if (!iso) return null;
  const t = Date.parse(iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z'));
  if (isNaN(t)) return null;
  return Math.max(0, Math.round((Date.now() - t) / 60000));
}
function staleMinutes(iso) { const m = minutesAgo(iso); return m != null && m > 20; }

function buildLegend() {
  document.getElementById('legend').innerHTML =
    '<strong style="font-size:0.75rem;">Congestion</strong>' +
    Object.entries(DENSITY_COLORS).filter(([k]) => k !== 'unknown')
      .map(([k, c]) => `<div class="row"><span class="swatch" style="background:${c}"></span>${k[0].toUpperCase() + k.slice(1)}</div>`)
      .join('');
}

function renderCards(overview) {
  const o = overview || {};
  const dc = o.density_counts || {};
  const cards = [
    ['Avg score', o.average_score != null ? o.average_score.toFixed(1) : '—', '#e2e8f0'],
    ['Blocked', dc.blocked ?? '—', DENSITY_COLORS.blocked],
    ['Heavy', dc.heavy ?? '—', DENSITY_COLORS.heavy],
    ['Moderate', dc.moderate ?? '—', DENSITY_COLORS.moderate],
    ['Light', dc.light ?? '—', DENSITY_COLORS.light],
    ['Cameras', o.camera_count ?? CAMERAS.length, '#e2e8f0'],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v" style="color:${c}">${v}</div></div>`).join('');
}

function renderList() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  const rows = CAMERAS
    .filter(cam => !q || [cam.name, cam.district, cam.sub_district, cam.camera_id]
      .some(v => (v || '').toString().toLowerCase().includes(q)))
    .sort((a, b) => {
      const pa = DENSITY_ORDER[a.latest_density] ?? -1, pb = DENSITY_ORDER[b.latest_density] ?? -1;
      if (pa !== pb) return pb - pa;
      return (b.latest_congestion_score ?? -1) - (a.latest_congestion_score ?? -1);
    });
  document.getElementById('camera-list').innerHTML = rows.map(cam => {
    const color = densityColor(cam.latest_density);
    const score = cam.latest_congestion_score;
    const m = minutesAgo(cam.latest_captured_at);
    const stale = staleMinutes(cam.latest_captured_at)
      ? `<span class="stale-badge">stale${m != null ? ' · ' + m + 'm' : ''}</span>` : '';
    return `<div class="cam-row" onclick="openDetail('${cam.camera_id}')">
      <span class="dot" style="background:${color}"></span>
      <div><div class="name">${cam.name || 'Camera ' + cam.camera_id}${stale}</div>
        <div class="sub">${[cam.district, cam.sub_district].filter(Boolean).join(' · ') || 'Location pending'}</div></div>
      <span class="score-pill" style="background:${color}">${score != null ? Math.round(score) : '—'}</span>
    </div>`;
  }).join('') || '<p class="muted">No cameras match.</p>';
}

function clearMarkers() { markers.forEach(m => map.removeLayer(m)); markers = []; }

function addMarkers(cameras) {
  clearMarkers();
  cameras.forEach(cam => {
    const pos = cam.map_position || {};
    const lat = cam.latitude != null ? cam.latitude : pos.latitude;
    const lon = cam.longitude != null ? cam.longitude : pos.longitude;
    if (lat == null || lon == null) return;
    const color = densityColor(cam.latest_density);
    const score = cam.latest_congestion_score;
    const icon = L.divIcon({
      className: '',
      html: `<div style="display:flex;flex-direction:column;align-items:center;">
          <div style="background:${color};width:16px;height:16px;border-radius:50%;border:3px solid rgba(15,23,42,0.9);box-shadow:0 0 0 5px rgba(0,0,0,0.12);cursor:pointer;"></div>
          ${score != null ? `<div style="font-size:0.58rem;font-weight:700;color:#0f172a;background:${color};border-radius:6px;padding:0 4px;margin-top:2px;">${Math.round(score)}</div>` : ''}
        </div>`,
      iconSize: [34, 32], iconAnchor: [17, 14]
    });
    const marker = L.marker([lat, lon], { icon }).addTo(map);
    marker.on('click', () => openDetail(cam.camera_id));
    markers.push(marker);
  });
}

function scoreChart(history) {
  const pts = (history || [])
    .map(h => ({ s: typeof h.congestion_score === 'number' ? h.congestion_score : null }))
    .filter(p => p.s != null);
  if (pts.length < 2) return '<p class="muted">Not enough history with scores.</p>';
  const w = 330, h = 84, pad = 8;
  const step = (w - pad * 2) / (pts.length - 1);
  const y = v => h - pad - (v / 100) * (h - pad * 2);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${(pad + i * step).toFixed(1)},${y(p.s).toFixed(1)}`).join(' ');
  const dots = pts.map((p, i) =>
    `<circle cx="${(pad + i * step).toFixed(1)}" cy="${y(p.s).toFixed(1)}" r="3" fill="${scoreColor(p.s)}"/>`).join('');
  const guides = [25, 50, 75].map(g =>
    `<line x1="${pad}" y1="${y(g)}" x2="${w - pad}" y2="${y(g)}" stroke="rgba(148,163,184,0.18)" stroke-dasharray="3 4"/>
     <text x="${w - pad}" y="${(y(g) - 3).toFixed(1)}" fill="#64748b" font-size="7" text-anchor="end">${g}</text>`).join('');
  return `<svg id="chart" viewBox="0 0 ${w} ${h}">${guides}<path d="${line}" fill="none" stroke="#38bdf8" stroke-width="2"/>${dots}</svg>`;
}

async function openDetail(id) {
  const panel = document.getElementById('detail-panel');
  const content = document.getElementById('detail-content');
  panel.classList.add('open');
  content.innerHTML = '<p class="muted">Loading…</p>';
  try {
    const [detail, history] = await Promise.all([
      fetch(`/api/cameras/${encodeURIComponent(id)}`).then(r => r.json()),
      fetch(`/api/cameras/${encodeURIComponent(id)}/history?limit=24`).then(r => r.ok ? r.json() : [])
    ]);
    const color = densityColor(detail.density);
    const imageSection = detail.latest_image_url
      ? `<div class="section"><h3>Latest frame</h3><img class="frame-preview" src="${detail.latest_image_url}"></div>`
      : '<div class="section"><h3>Latest frame</h3><p class="muted">No saved frame available.</p></div>';
    // Crossings are per-burst observations — hide the section when zero.
    const split = detail.flow_rate_vph || {};
    const tot = (split.in || 0) + (split.out || 0);
    const flowSection = tot
      ? `<div class="section"><h3>Crossings this burst</h3>
           <div class="flowbar"><div class="nb" style="width:${Math.round((split.in||0)/tot*100)}%">in ${split.in||0}</div>
           <div class="sb" style="width:${100 - Math.round((split.in||0)/tot*100)}%">out ${split.out||0}</div></div></div>`
      : '';
    content.innerHTML = `
      <h2>${detail.name || 'Camera ' + detail.camera_id}</h2>
      <p class="sub">ID ${detail.camera_id} · ${[detail.district, detail.sub_district].filter(Boolean).join(' · ') || 'Location pending'}</p>
      <span class="density-badge" style="background:${color}">${(detail.density || 'unknown').toUpperCase()}</span>
      <span style="margin-left:8px;font-weight:700;">Score ${detail.congestion_score != null ? detail.congestion_score : '—'}/100</span>
      ${imageSection}
      <div class="stat-grid">
        <div class="stat"><div class="k">Vehicles (mean)</div><div class="v">${detail.vehicle_count ?? '—'}</div></div>
        <div class="stat"><div class="k">Coverage</div><div class="v">${typeof detail.coverage_ratio === 'number' ? (detail.coverage_ratio * 100).toFixed(1) + '%' : '—'}</div></div>
        <div class="stat"><div class="k">Confidence</div><div class="v">${detail.mean_confidence != null ? (detail.mean_confidence * 100).toFixed(0) + '%' : '—'}</div></div>
        <div class="stat"><div class="k">Scene</div><div class="v">${[detail.lighting, detail.quality_flag].filter(Boolean).join('/') || '—'}</div></div>
      </div>
      <div class="section"><h3>Congestion trend (score)</h3>${Array.isArray(history) ? scoreChart(history) : '<p class="muted">No history.</p>'}</div>
      ${flowSection}
      <div class="section"><h3>Captured</h3><p class="muted">${detail.captured_at || 'unknown'}${staleMinutes(detail.captured_at) ? ' · <span style="color:#fca5a5">stale</span>' : ''}</p></div>
      ${detail.stream_url ? `<div class="section"><h3>Stream</h3><span class="stream-link">${detail.stream_url}</span></div>` : ''}
    `;
  } catch (e) {
    content.innerHTML = `<p class="muted">Failed to load detail for camera ${id}.</p>`;
  }
}
window.openDetail = openDetail;

async function refresh() {
  const status = document.getElementById('status');
  try {
    const res = await fetch('/api/cameras');
    CAMERAS = await res.json();
    addMarkers(CAMERAS);
    renderList();
    let overview = null;
    try { overview = await fetch('/api/overview').then(r => r.json()); } catch (_) {}
    renderCards(overview);
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
document.getElementById('search').addEventListener('input', renderList);

buildLegend();
renderCards(INITIAL.overview);
addMarkers(CAMERAS);
renderList();
document.getElementById('status').textContent = 'Loaded ' + CAMERAS.length + ' cameras';
setupAutoRefresh();
</script>
</body>
</html>
"""
