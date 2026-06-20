from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

DEFAULT_INDEX_URL = "https://www.dsat.gov.mo/dsat/realtime.aspx"
REQUEST_HEADERS = {
    "User-Agent": "traffic-cam-ai-test/1.0 (+https://github.com/mrvictoru/traffic-cam-ai-test)"
}

CAMERA_URL_RE = re.compile(
    r"(?P<url>(?:https?://|/)?[^\"'\s>]*realtime_core\.aspx\?[^\"'\s>]*cam_id=(?P<cam_id>\d+)[^\"'\s>]*)",
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


@dataclass
class CameraEntry:
    cam_id: str
    detail_url: str
    name: str | None = None


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


def fetch_text(url: str) -> str:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


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


def build_feed_snapshot(
    index_url: str = DEFAULT_INDEX_URL,
    fetcher: Callable[[str], str] = fetch_text,
) -> dict:
    index_html = fetcher(index_url)
    cameras = extract_camera_entries(index_html, index_url)

    snapshot_cameras = []
    for camera in cameras:
        camera_payload = {
            "cam_id": camera.cam_id,
            "name": camera.name,
            "detail_url": camera.detail_url,
            "stream_urls": [],
        }
        try:
            detail_html = fetcher(camera.detail_url)
            camera_payload["stream_urls"] = extract_stream_urls(detail_html, camera.detail_url)
        except Exception as exc:  # pragma: no cover - exercised in live use
            camera_payload["fetch_error"] = str(exc)
        snapshot_cameras.append(camera_payload)

    return {
        "source_url": index_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "camera_count": len(snapshot_cameras),
        "cameras": snapshot_cameras,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the Macau DSAT realtime traffic camera feed index and resolve live stream URLs."
    )
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL, help="DSAT realtime index page URL.")
    parser.add_argument("--limit", type=int, default=None, help="Only print the first N cameras.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    args = parser.parse_args()

    snapshot = build_feed_snapshot(index_url=args.index_url)
    if args.limit is not None:
        snapshot["cameras"] = snapshot["cameras"][: args.limit]
        snapshot["camera_count"] = len(snapshot["cameras"])

    dump_args = {"ensure_ascii": False}
    if args.pretty:
        dump_args["indent"] = 2
    print(json.dumps(snapshot, **dump_args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
