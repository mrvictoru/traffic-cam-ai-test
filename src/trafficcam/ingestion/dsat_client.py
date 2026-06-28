"""Client for discovering camera feeds from the DSAT website."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable, List
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..models import CameraFeed

DEFAULT_INDEX_URL = "https://www.dsat.gov.mo/dsat/realtime.aspx"
REQUEST_HEADERS = {
    "User-Agent": "traffic-cam-ai-test/1.0 (+https://github.com/mrvictoru/traffic-cam-ai-test)"
}

CAMERA_URL_RE = re.compile(
    r"(?P<url>(?:https?://|/)?[^\"'\s>]*realtime_(?:core(?:4)?|reload)\.aspx\?[^\"'\s>]*cam_id=(?P<cam_id>\d+)[^\"'\s>]*)",
    re.IGNORECASE,
)
DISTRICT_RE = re.compile(
    r"class=\"area_button\"[^>]*>(?P<district>[^<]+)<",
    re.IGNORECASE,
)
# Top-level district buttons map to sub-district groups via onclick show_sub('s_N').
AREA_BUTTON_RE = re.compile(
    r"id=\"area\d+\"[^>]*onclick=\"show\(\d+\);show_sub\('(?P<subid>s_\d+)'\)\"[^>]*>(?P<district>[^<]+)<",
    re.IGNORECASE,
)
# Sub-district section headers carry the neighborhood name and wrap camera rows.
SUB_DISTRICT_RE = re.compile(
    r"id=\"sub_tab_(?P<subid>s_\d+)\"[^>]*>\s*<div><img[^>]*>&nbsp;(?P<subname>[^<]+)</div>",
    re.IGNORECASE,
)
# Top-level district tab wrappers (macau_tab, cotai_tab, bridge_tab, a_tab, border_tab).
# Button order maps 1:1 to these tabs in document order.
DISTRICT_TAB_RE = re.compile(
    r"<div[^>]*id=\"(?P<tabid>macau_tab|cotai_tab|bridge_tab|a_tab|border_tab)\"[^>]*>",
    re.IGNORECASE,
)
RELOAD_REDIRECT_RE = re.compile(
    r"<a[^>]+href=[\"'](?P<url>(?:https?://|/)?[^\"'\s>]*realtime_(?:core(?:4)?|reload)\.aspx\?[^\"'\s>]*cam_id=\d+)[\"'][^>]*>",
    re.IGNORECASE,
)
META_REFRESH_RE = re.compile(
    r"<meta[^>]+http-equiv=[\"']refresh[\"'][^>]+content=[\"'][^;]+;\s*url=(?P<url>[^\"'\s>]+)[\"']",
    re.IGNORECASE,
)
STREAM_URL_RE = re.compile(r"https?://[^\"'\s>]+\.m3u8(?:\?[^\"'\s>]*)?", re.IGNORECASE)
IMAGE_URL_RE = re.compile(
    r"(?P<url>(?:https?://|/)?[^\"'\s>]*image\.aspx\?[^\"'\s>]*src=[^\"'\s>&]+[^\"'\s>]*)",
    re.IGNORECASE,
)
SNAPSHOT_URL_RE = re.compile(
    r"(?P<url>(?:https?://|/)?[^\"'\s>]+\.(?:jpg|jpeg|png)(?:\?[^\"'\s>]*)?)",
    re.IGNORECASE,
)


class CameraEntry:
    def __init__(
        self,
        cam_id: str,
        detail_url: str,
        name: str | None = None,
        district: str | None = None,
        sub_district: str | None = None,
    ) -> None:
        self.cam_id = cam_id
        self.detail_url = detail_url
        self.name = name
        self.district = district
        self.sub_district = sub_district


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.anchors: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value for key, value in attrs if value}
        href = attr_map.get("href")
        if not href:
            return
        self._current_href = href
        self._current_parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        text = " ".join(part.strip() for part in self._current_parts if part.strip()).strip()
        self.anchors.append((self._current_href, text))
        self._current_href = None
        self._current_parts = []


class DSATClient:
    """Client for discovering camera feeds from the DSAT website."""

    def __init__(self, index_url: str | None = None, fetcher: Callable[[str], str] | None = None) -> None:
        self.index_url = index_url or DEFAULT_INDEX_URL
        self.fetcher = fetcher or self._fetch_text

    def _fetch_text(self, url: str) -> str:
        request = Request(url, headers=REQUEST_HEADERS)
        with urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    def discover_cameras(self, limit: int | None = None) -> List[CameraFeed]:
        manifest = self.build_manifest(limit=limit)
        return [
            CameraFeed(
                camera_id=str(camera["cam_id"]),
                name=camera.get("name"),
                detail_url=camera["detail_url"],
                stream_url=(camera.get("stream_urls") or [None])[0],
                metadata={
                    "source": "dsat",
                    "district": camera.get("district"),
                    "sub_district": camera.get("sub_district"),
                },
            )
            for camera in manifest["cameras"]
        ]

    def build_manifest(self, limit: int | None = None) -> dict:
        index_html = self.fetcher(self.index_url)
        cameras = extract_camera_entries(index_html, self.index_url)

        snapshot_cameras = []
        for camera in cameras:
            camera_payload = {
                "cam_id": camera.cam_id,
                "name": camera.name,
                "district": camera.district,
                "sub_district": camera.sub_district,
                "detail_url": camera.detail_url,
                "stream_urls": [],
            }
            try:
                detail_html = self.fetcher(camera.detail_url)
                stream_urls = extract_stream_urls(detail_html, camera.detail_url)
                if not stream_urls:
                    redirect_url = _follow_reload_page(detail_html, camera.detail_url)
                    if redirect_url and redirect_url != camera.detail_url:
                        detail_html = self.fetcher(redirect_url)
                        stream_urls = extract_stream_urls(detail_html, redirect_url)
                camera_payload["stream_urls"] = stream_urls
            except Exception as exc:  # pragma: no cover - exercised in live use
                camera_payload["fetch_error"] = str(exc)
            snapshot_cameras.append(camera_payload)

        if limit is not None:
            snapshot_cameras = snapshot_cameras[:limit]

        return {
            "source_url": self.index_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "camera_count": len(snapshot_cameras),
            "cameras": snapshot_cameras,
        }

    def normalize_detail_url(self, detail_url: str) -> str:
        """Normalize a detail URL to a consistent form."""
        parsed = urlparse(detail_url)
        return parsed.geturl()


def _normalize_url(url: str, base_url: str) -> str:
    # DSAT index pages HTML-encode ampersands in href attributes as &amp;.
    # Unescape them so the detail URL is fetchable.
    return urljoin(base_url, url.replace("&amp;", "&"))


def _normalize_district(value: str) -> str:
    """Trim and collapse whitespace in a district header."""
    return re.sub(r"\s+", " ", value or "").strip()


def extract_camera_entries(html: str, base_url: str) -> list[CameraEntry]:
    """Extract camera entries from a DSAT index page, preserving location metadata.

    The DSAT page groups cameras under:
    - Top-level district buttons (e.g. "澳門區", "路氹區", "跨海大橋",
      "新城A區", "口岸") which reference sub-district groups via
      ``onclick="show(N);show_sub('s_X')"``.
    - Sub-district sections (``id="sub_tab_s_N"``) that carry a neighborhood
      name (e.g. "青洲區、筷子基區及林茂塘區") and wrap the camera rows
      for that neighborhood.

    Each camera is attributed to:
    - ``sub_district``: the neighborhood name of the sub-district section that
      wraps it in document order.
    - ``district``: the top-level district whose area-button references a
      sub-district with the same id, falling back to the area-button whose
      sub-district id precedes the camera in document order.
    - ``name``: the camera link text (e.g. an intersection or road name).
    """
    cameras: dict[str, CameraEntry] = {}

    # Map each sub-district id -> (section start position, neighborhood name)
    sub_sections: list[tuple[int, str, str]] = []
    for m in SUB_DISTRICT_RE.finditer(html):
        sub_sections.append((m.start(), m.group("subid"), _normalize_district(m.group("subname"))))

    # Map each area-button's referenced sub-district id -> top-level district name
    district_by_subid: dict[str, str] = {}
    for m in AREA_BUTTON_RE.finditer(html):
        district_by_subid[m.group("subid")] = _normalize_district(m.group("district"))

    # District tab wrappers define the intervals that group sub-district sections.
    # The 5 buttons (show(1..5)) map 1:1 to the tabs in document order:
    # macau_tab (1=澳門區), cotai_tab (2=路氹區), bridge_tab (3=跨海大橋),
    # a_tab (4=新城A區), border_tab (5=口岸).
    tab_ids = ["macau_tab", "cotai_tab", "bridge_tab", "a_tab", "border_tab"]
    tab_positions: list[tuple[int, str]] = []
    for m in DISTRICT_TAB_RE.finditer(html):
        tab_positions.append((m.start(), m.group("tabid")))

    # Area buttons in document order give us the district names aligned to tabs.
    area_button_districts: list[str] = [
        _normalize_district(m.group("district")) for m in AREA_BUTTON_RE.finditer(html)
    ]
    tab_to_district: dict[str, str] = {}
    for idx, tabid in enumerate(tab_ids):
        if idx < len(area_button_districts):
            tab_to_district[tabid] = area_button_districts[idx]

    # Build intervals: each tab spans from its position to the next tab's position.
    tab_intervals: list[tuple[int, int, str]] = []
    for idx, (pos, tabid) in enumerate(tab_positions):
        end = tab_positions[idx + 1][0] if idx + 1 < len(tab_positions) else len(html)
        tab_intervals.append((pos, end, tab_to_district.get(tabid, "")))

    def district_for_position(pos: int) -> str | None:
        for start, end, name in tab_intervals:
            if start <= pos < end:
                return name or None
        return None

    def sub_district_for_position(pos: int) -> tuple[str | None, str | None]:
        """Return (sub_district_name, district_name) for a camera at `pos`."""
        current_subid: str | None = None
        current_subname: str | None = None
        for section_pos, subid, subname in sub_sections:
            if section_pos <= pos:
                current_subid = subid
                current_subname = subname
            else:
                break
        # Prefer the explicit button mapping, fall back to the tab interval.
        district = district_by_subid.get(current_subid) if current_subid else None
        if district is None:
            district = district_for_position(pos)
        return current_subname, district

    parser = AnchorParser()
    parser.feed(html)

    # Build a map of cam_id -> link text from the anchor parser (which gives us
    # the display name but not the source position).
    cam_text_by_id: dict[str, str | None] = {}
    for href, text in parser.anchors:
        match = CAMERA_URL_RE.search(href)
        if not match:
            continue
        cam_id = match.group("cam_id")
        if cam_text_by_id.get(cam_id) is None and text:
            cam_text_by_id[cam_id] = text

    # Scan the raw HTML for camera link positions so we can attribute each
    # camera to the sub-district section and tab interval that contains it.
    for match in CAMERA_URL_RE.finditer(html):
        cam_id = match.group("cam_id")
        if cam_id in cameras:
            continue
        sub_name, district = sub_district_for_position(match.start())
        cameras[cam_id] = CameraEntry(
            cam_id=cam_id,
            detail_url=_normalize_url(match.group("url"), base_url),
            name=cam_text_by_id.get(cam_id),
            district=district,
            sub_district=sub_name,
        )

    return sorted(cameras.values(), key=lambda camera: int(camera.cam_id))


def extract_stream_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    for pattern in (STREAM_URL_RE, IMAGE_URL_RE, SNAPSHOT_URL_RE):
        for match in pattern.finditer(html):
            candidate = match.groupdict().get("url", match.group(0))
            normalized = _normalize_url(candidate, base_url)
            if normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)

    return urls


def _follow_reload_page(html: str, base_url: str) -> str | None:
    match = RELOAD_REDIRECT_RE.search(html)
    if match:
        return _normalize_url(match.group("url"), base_url)

    match = META_REFRESH_RE.search(html)
    if match:
        return _normalize_url(match.group("url"), base_url)

    return None
