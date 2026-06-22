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
    def __init__(self, cam_id: str, detail_url: str, name: str | None = None) -> None:
        self.cam_id = cam_id
        self.detail_url = detail_url
        self.name = name


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
                metadata={"source": "dsat"},
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
    return urljoin(base_url, url)


def extract_camera_entries(html: str, base_url: str) -> list[CameraEntry]:
    parser = AnchorParser()
    parser.feed(html)

    cameras: dict[str, CameraEntry] = {}
    for href, text in parser.anchors:
        match = CAMERA_URL_RE.search(href)
        if not match:
            continue
        cam_id = match.group("cam_id")
        entry = cameras.setdefault(
            cam_id,
            CameraEntry(
                cam_id=cam_id,
                detail_url=_normalize_url(match.group("url"), base_url),
                name=text or None,
            ),
        )
        if not entry.name and text:
            entry.name = text

    for match in CAMERA_URL_RE.finditer(html):
        cam_id = match.group("cam_id")
        cameras.setdefault(
            cam_id,
            CameraEntry(
                cam_id=cam_id,
                detail_url=_normalize_url(match.group("url"), base_url),
            ),
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
