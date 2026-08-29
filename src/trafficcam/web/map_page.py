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
    use_background_refresh = store is None
    if store is None:
        store = JsonStore("data")
    summaries = build_camera_summaries(store=store)
    try:
        overview = get_overview() if use_background_refresh else get_overview(store=store)
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
    #traffic-notice {
      display: flex; align-items: center; gap: 9px; min-height: 36px; padding: 7px 16px;
      font-size: 0.78rem; border-bottom: 1px solid rgba(148,163,184,0.2);
    }
    #traffic-notice.live { background: #052e16; color: #bbf7d0; }
    #traffic-notice.provisional { background: #422006; color: #fde68a; }
    #traffic-notice.historical { background: #450a0a; color: #fecaca; }
    #traffic-notice strong { color: inherit; }
    #calibration-panel {
      padding: 8px 16px 10px; border-bottom: 1px solid rgba(148,163,184,0.2);
      background: rgba(15,23,42,0.94); font-size: 0.76rem;
    }
    #calibration-panel .cal-head { display:flex; justify-content:space-between; gap:12px; align-items:baseline; margin-bottom:4px; }
    #calibration-panel .cal-task { display:flex; gap:8px; align-items:flex-start; margin:3px 0; color:#cbd5e1; }
    .owner-pill { font-size:0.62rem; border-radius:6px; padding:1px 6px; text-transform:uppercase; letter-spacing:0.04em; flex-shrink:0; margin-top:2px; }
    .owner-pill.human { color:#fde68a; background:rgba(161,98,7,0.28); border:1px solid rgba(250,204,21,0.4); }
    .owner-pill.automated { color:#7dd3fc; background:rgba(7,89,133,0.28); border:1px solid rgba(56,189,248,0.4); }
    .task-status { font-size:0.62rem; color:#94a3b8; }
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
    .approx-badge {
      font-size: 0.62rem; color: #fde68a; background: rgba(202,138,4,0.18);
      border: 1px solid rgba(202,138,4,0.45); border-radius: 6px; padding: 1px 6px; margin-left: 6px;
    }
    .trust-badge {
      font-size: 0.62rem; border-radius: 6px; padding: 1px 6px; margin-left: 6px;
      color: #cbd5e1; background: rgba(71,85,105,0.35); border: 1px solid rgba(148,163,184,0.35);
    }
    .trust-badge.live { color: #bbf7d0; background: rgba(22,101,52,0.35); border-color: rgba(74,222,128,0.45); }
    .trust-badge.provisional { color: #fde68a; background: rgba(161,98,7,0.3); border-color: rgba(250,204,21,0.45); }
    .reliability-panel {
      margin: 12px 0; padding: 10px 12px; border-radius: 10px; font-size: 0.76rem;
      background: rgba(71,85,105,0.25); border: 1px solid rgba(148,163,184,0.3);
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
      <button class="btn" id="edit-mode-btn" type="button">✎ Edit positions</button>
      <label class="btn" style="display:flex;gap:6px;align-items:center;cursor:pointer;">
        <input type="checkbox" id="auto-refresh" checked style="margin:0;"> Auto
      </label>
      <label class="btn" style="display:flex;gap:6px;align-items:center;cursor:pointer;">
        <input type="checkbox" id="show-approximate" style="margin:0;"> Approx markers
      </label>
    </div>
  </header>
  <div id="traffic-notice" class="historical">
    <strong>Checking live coverage…</strong>
  </div>
  <div id="calibration-panel" hidden></div>
  <main>
    <aside id="sidebar">
      <div style="display:grid;grid-template-columns:1fr auto;gap:7px;">
        <input id="search" type="text" placeholder="Search camera or district…">
        <select id="traffic-filter" class="btn" aria-label="Traffic availability">
          <option value="all">All cameras</option>
          <option value="live">Live only</option>
          <option value="attention">Needs attention</option>
        </select>
      </div>
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
let CORRIDOR_SEGMENTS = (INITIAL.overview && INITIAL.overview.corridor_segments) || [];
const map = L.map('map', { zoomControl: true }).setView([22.169, 113.555], 13);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

let markers = [];
let corridorLayers = [];
let refreshTimer = null;
let editModeEnabled = false;

function densityColor(d) { return DENSITY_COLORS[(d || 'unknown').toLowerCase()] || DENSITY_COLORS.unknown; }
function reliability(cam) { return cam.traffic_reliability || { level: 'unavailable', is_live: false }; }
function displayDensity(cam) { return reliability(cam).is_live ? cam.latest_density : 'unknown'; }
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
function hasApproximatePosition(cam) {
  return ((cam.map_position || {}).source || 'approximate') !== 'coordinates';
}
function approximateCameraCount() {
  return CAMERAS.filter(hasApproximatePosition).length;
}
function setStatus(message) {
  document.getElementById('status').textContent = message;
}

function buildLegend() {
  document.getElementById('legend').innerHTML =
    '<strong style="font-size:0.75rem;">Live traffic</strong>' +
    Object.entries(DENSITY_COLORS).filter(([k]) => k !== 'unknown')
      .map(([k, c]) => `<div class="row"><span class="swatch" style="background:${c}"></span>${k[0].toUpperCase() + k.slice(1)}</div>`)
      .join('') +
    `<div class="row"><span class="swatch" style="background:${DENSITY_COLORS.unknown}"></span>Stale / no data</div>` +
    '<div style="max-width:150px;margin-top:6px;color:#94a3b8;font-size:0.65rem;">Colours apply only to observations from the last 20 minutes. Dashed roads are historical or provisional. Approximate camera locations are hidden by default.</div>';
}

function renderCards(overview) {
  const o = overview || {};
  const dc = o.live_density_counts || {};
  const rc = o.reliability_counts || {};
  const calibration = o.calibration_summary || {};
  const cards = [
    ['Live now', o.live_camera_count ?? 0, '#4ade80'],
    ['Live avg', o.live_average_score != null ? o.live_average_score.toFixed(1) : '—', '#e2e8f0'],
    ['Blocked', dc.blocked ?? '—', DENSITY_COLORS.blocked],
    ['Heavy', dc.heavy ?? '—', DENSITY_COLORS.heavy],
    ['Stale', rc.stale ?? '—', '#fca5a5'],
    ['No data', rc.unavailable ?? '—', '#94a3b8'],
    ['Calibrated', calibration.configured ?? '—', '#38bdf8'],
    ['Need you', (o.human_calibration || {}).human_remaining ?? '—', '#fde68a'],
  ];
  document.getElementById('cards').innerHTML = cards.map(([k, v, c]) =>
    `<div class="card"><div class="k">${k}</div><div class="v" style="color:${c}">${v}</div></div>`).join('');

  const notice = document.getElementById('traffic-notice');
  const liveCount = o.live_camera_count ?? 0;
  const reliableCount = rc.reliable ?? 0;
  if (!liveCount) {
    notice.className = 'historical';
    notice.innerHTML = `<strong>Historical view — no current traffic observations.</strong> Latest scores are older than ${o.live_max_age_minutes ?? 20} minutes and are shown in grey, not as live conditions.`;
  } else if (!reliableCount) {
    notice.className = 'provisional';
    notice.innerHTML = `<strong>Live but provisional.</strong> ${liveCount} cameras are current, but none are calibrated against free-flow speed yet. Use colours as estimates, not routing-grade traffic.`;
  } else {
    notice.className = 'live';
    notice.innerHTML = `<strong>Live coverage:</strong> ${liveCount}/${o.camera_count ?? CAMERAS.length} cameras current · ${reliableCount} calibrated and reliable.`;
  }
  renderCalibrationPanel(o.human_calibration);
}

function renderCalibrationPanel(calibration) {
  const panel = document.getElementById('calibration-panel');
  if (!panel) return;
  if (!calibration || !Array.isArray(calibration.tasks) || !calibration.tasks.length) {
    panel.hidden = true;
    panel.innerHTML = '';
    return;
  }
  const windowInfo = calibration.offpeak_window || {};
  const human = calibration.tasks.filter(task => task.owner === 'human' && task.status !== 'done');
  const headline = calibration.human_required
    ? `Human calibration required — ${calibration.human_remaining} map/ROI/corridor items still need a person.`
    : 'No blocking human calibration items.';
  const windowLabel = windowInfo.in_offpeak_window
    ? '02:00–05:00 Asia/Macau collection window is open now. Evening/daytime captures cannot be used as free-flow speeds.'
    : `Free-flow collection window is 02:00–05:00 Asia/Macau. Next window ${windowInfo.next_window_start || 'tonight'}; do not run calibrate-freeflow until then.`;
  panel.hidden = false;
  panel.innerHTML =
    `<div class="cal-head"><strong>${headline}</strong><span class="muted">${windowLabel}</span></div>` +
    calibration.tasks.map(task => {
      const remaining = task.remaining ? ` · ${task.remaining} remaining` : '';
      return `<div class="cal-task"><span class="owner-pill ${task.owner}">${task.owner}</span><div><div>${task.title} <span class="task-status">${task.status}${remaining}</span></div><div class="muted">${task.detail || ''} ${task.action || ''}</div></div></div>`;
    }).join('') +
    (human.length ? '<div class="muted" style="margin-top:4px;">Use Edit positions for camera placement. ROI, flow-line, and corridor geometry still need a person looking at the actual road.</div>' : '');
}

function renderList() {
  const q = document.getElementById('search').value.trim().toLowerCase();
  const filter = document.getElementById('traffic-filter').value;
  const rows = CAMERAS
    .filter(cam => !q || [cam.name, cam.district, cam.sub_district, cam.camera_id]
      .some(v => (v || '').toString().toLowerCase().includes(q)))
    .filter(cam => filter === 'all' || (filter === 'live' ? reliability(cam).is_live : !reliability(cam).is_live))
    .sort((a, b) => {
      if (reliability(a).is_live !== reliability(b).is_live) return reliability(b).is_live ? 1 : -1;
      const pa = DENSITY_ORDER[displayDensity(a)] ?? -1, pb = DENSITY_ORDER[displayDensity(b)] ?? -1;
      if (pa !== pb) return pb - pa;
      return (b.latest_congestion_score ?? -1) - (a.latest_congestion_score ?? -1);
    });
  document.getElementById('camera-list').innerHTML = rows.map(cam => {
    const trust = reliability(cam);
    const color = densityColor(displayDensity(cam));
    const score = cam.latest_congestion_score;
    const m = minutesAgo(cam.latest_captured_at);
    const freshness = trust.is_live
      ? `<span class="trust-badge ${trust.level === 'reliable' ? 'live' : 'provisional'}">${trust.level}</span>`
      : `<span class="stale-badge">${trust.level}${m != null ? ' · ' + m + 'm' : ''}</span>`;
    const approx = hasApproximatePosition(cam) ? '<span class="approx-badge">needs placement</span>' : '';
    return `<div class="cam-row" onclick="openDetail('${cam.camera_id}')">
      <span class="dot" style="background:${color}"></span>
      <div><div class="name">${cam.name || 'Camera ' + cam.camera_id}${freshness}${approx}</div>
        <div class="sub">${[cam.district, cam.sub_district].filter(Boolean).join(' · ') || 'Location pending'}</div></div>
      <span class="score-pill" style="background:${color};opacity:${trust.is_live ? 1 : 0.65}">${trust.is_live && score != null ? Math.round(score) : '—'}</span>
    </div>`;
  }).join('') || '<p class="muted">No cameras match.</p>';
}

function clearMarkers() { markers.forEach(m => map.removeLayer(m)); markers = []; }

function clearSegments() { corridorLayers.forEach(layer => map.removeLayer(layer)); corridorLayers = []; }

function addSegments(segments) {
  clearSegments();
  (segments || []).forEach(segment => {
    const start = segment.start || {};
    const end = segment.end || {};
    if (start.latitude == null || start.longitude == null || end.latitude == null || end.longitude == null) return;
    const color = segment.is_live ? densityColor(segment.density) : DENSITY_COLORS.unknown;
    const weight = segment.average_score != null ? Math.max(3, Math.min(8, Math.round(segment.average_score / 18))) : 4;
    const dashArray = segment.is_approximate || !segment.is_live || segment.reliability !== 'reliable' ? '8 6' : null;
    const polyline = L.polyline(
      [[start.latitude, start.longitude], [end.latitude, end.longitude]],
      {
        color,
        weight,
        opacity: segment.is_live ? (segment.is_approximate ? 0.55 : 0.9) : 0.45,
        dashArray,
      }
    ).addTo(map);
    const scoreLabel = segment.is_live && segment.average_score != null ? ` · score ${Math.round(segment.average_score)}` : '';
    const trustLabel = segment.is_live ? ` · ${segment.reliability}` : ' · historical';
    polyline.bindTooltip(
      `${segment.name || segment.sub_district || segment.district || 'Corridor'} · ${segment.is_live ? (segment.density || 'unknown').toUpperCase() : 'NO LIVE DATA'}${scoreLabel}${trustLabel}`,
      { sticky: true }
    );
    corridorLayers.push(polyline);
  });
}

async function saveCameraPosition(cameraId, latitude, longitude) {
  try {
    const response = await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/position`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ latitude, longitude })
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || 'Failed to save camera position');
    }
    const target = CAMERAS.find(cam => String(cam.camera_id) === String(cameraId));
    if (target) {
      target.latitude = payload.latitude;
      target.longitude = payload.longitude;
      target.map_position = payload.map_position;
    }
    setStatus(`Saved ${cameraId}`);
    refresh();
    return payload;
  } catch (error) {
    setStatus(error.message || 'Save failed');
    throw error;
  }
}

function addMarkers(cameras) {
  clearMarkers();
  cameras.forEach(cam => {
    if (hasApproximatePosition(cam) && !document.getElementById('show-approximate').checked) return;
    const pos = cam.map_position || {};
    const lat = cam.latitude != null ? cam.latitude : pos.latitude;
    const lon = cam.longitude != null ? cam.longitude : pos.longitude;
    if (lat == null || lon == null) return;
    const trust = reliability(cam);
    const color = densityColor(displayDensity(cam));
    const score = cam.latest_congestion_score;
    const icon = L.divIcon({
      className: '',
      html: `<div style="display:flex;flex-direction:column;align-items:center;">
          <div style="background:${color};width:${trust.is_live ? 16 : 11}px;height:${trust.is_live ? 16 : 11}px;border-radius:50%;border:3px solid rgba(15,23,42,0.9);opacity:${trust.is_live ? 1 : 0.55};cursor:pointer;"></div>
          ${trust.is_live && score != null ? `<div style="font-size:0.58rem;font-weight:700;color:#0f172a;background:${color};border-radius:6px;padding:0 4px;margin-top:2px;">${Math.round(score)}</div>` : ''}
        </div>`,
      iconSize: [34, 32], iconAnchor: [17, 14]
    });
    const marker = L.marker([lat, lon], { icon, draggable: editModeEnabled }).addTo(map);
    marker.on('click', () => {
      if (!editModeEnabled) openDetail(cam.camera_id);
    });
    if (editModeEnabled) {
      marker.on('dragend', async function () {
        const ll = marker.getLatLng();
        await saveCameraPosition(cam.camera_id, ll.lat, ll.lng);
      });
    }
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
      fetch(`/api/cameras/${encodeURIComponent(id)}`).then(async r => {
        const payload = await r.json();
        if (!r.ok) throw new Error(payload.detail || `Failed to load camera ${id}`);
        return payload;
      }),
      fetch(`/api/cameras/${encodeURIComponent(id)}/history?limit=24`).then(r => r.ok ? r.json() : [])
    ]);
    const trust = reliability(detail);
    const color = densityColor(trust.is_live ? detail.density : 'unknown');
    const approximate = ((detail.map_position || {}).source || 'approximate') !== 'coordinates';
    const imageSection = detail.latest_image_url
      ? `<div class="section"><h3>Latest frame</h3><img class="frame-preview" src="${detail.latest_image_url}"></div>`
      : `<div class="section"><h3>Latest frame</h3><p class="muted">${detail.captured_at ? 'No saved frame available.' : 'Waiting for the first capture and analysis cycle for this camera.'}</p></div>`;
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
      <p class="sub">ID ${detail.camera_id} · ${[detail.district, detail.sub_district].filter(Boolean).join(' · ') || 'Location pending'}${approximate ? ' · approximate placement' : ''}</p>
      <span class="density-badge" style="background:${color}">${trust.is_live ? (detail.density || 'unknown').toUpperCase() : 'NO LIVE DATA'}</span>
      <span style="margin-left:8px;font-weight:700;">${trust.is_live && detail.congestion_score != null ? `Score ${detail.congestion_score}/100` : 'Historical score hidden'}</span>
      ${approximate ? '<span class="approx-badge">drag in edit mode to place</span>' : ''}
      <div class="reliability-panel"><strong>${(trust.level || 'unavailable').replace('_', ' ').toUpperCase()}</strong><br>${trust.reason || 'Traffic reliability is unknown.'}${trust.age_minutes != null ? ` · observed ${trust.age_minutes} minutes ago` : ''}</div>
      ${imageSection}
      <div class="stat-grid">
        <div class="stat"><div class="k">Vehicles (mean)</div><div class="v">${detail.vehicle_count ?? '—'}</div></div>
        <div class="stat"><div class="k">Coverage</div><div class="v">${typeof detail.coverage_ratio === 'number' ? (detail.coverage_ratio * 100).toFixed(1) + '%' : '—'}</div></div>
        <div class="stat"><div class="k">Confidence</div><div class="v">${detail.mean_confidence != null ? (detail.mean_confidence * 100).toFixed(0) + '%' : '—'}</div></div>
        <div class="stat"><div class="k">Scene</div><div class="v">${[detail.lighting, detail.quality_flag].filter(Boolean).join('/') || '—'}</div></div>
      </div>
      <div class="section"><h3>Historical congestion trend</h3>${Array.isArray(history) ? scoreChart(history) : '<p class="muted">No history.</p>'}</div>
      ${flowSection}
      <div class="section"><h3>Captured</h3><p class="muted">${detail.captured_at || 'unknown'}${staleMinutes(detail.captured_at) ? ' · <span style="color:#fca5a5">stale</span>' : ''}</p></div>
      ${detail.stream_url ? `<div class="section"><h3>Stream</h3><span class="stream-link">${detail.stream_url}</span></div>` : ''}
    `;
  } catch (e) {
    content.innerHTML = `<p class="muted">${e.message || `Failed to load detail for camera ${id}.`}</p>`;
  }
}
window.openDetail = openDetail;

async function refresh() {
  const status = document.getElementById('status');
  try {
    const res = await fetch('/api/cameras');
    CAMERAS = await res.json();
    let overview = null;
    try { overview = await fetch('/api/overview').then(r => r.json()); } catch (_) {}
    CORRIDOR_SEGMENTS = (overview && overview.corridor_segments) || [];
    addSegments(CORRIDOR_SEGMENTS);
    addMarkers(CAMERAS);
    renderList();
    renderCards(overview);
    setStatus('Updated ' + new Date().toLocaleTimeString());
  } catch (e) {
    setStatus('Refresh failed');
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
document.getElementById('traffic-filter').addEventListener('change', renderList);
document.getElementById('show-approximate').addEventListener('change', () => addMarkers(CAMERAS));
document.getElementById('edit-mode-btn').addEventListener('click', () => {
  editModeEnabled = !editModeEnabled;
  document.getElementById('edit-mode-btn').textContent = editModeEnabled ? '✓ Editing' : '✎ Edit positions';
  document.getElementById('auto-refresh').checked = !editModeEnabled;
  if (editModeEnabled) {
    setStatus('Drag a marker to reposition it');
  } else {
    setStatus('Editing off');
  }
  setupAutoRefresh();
  addMarkers(CAMERAS);
});

buildLegend();
renderCards(INITIAL.overview);
addSegments(CORRIDOR_SEGMENTS);
addMarkers(CAMERAS);
renderList();
setStatus('Loaded ' + CAMERAS.length + ' cameras');
setupAutoRefresh();
</script>
</body>
</html>
"""
