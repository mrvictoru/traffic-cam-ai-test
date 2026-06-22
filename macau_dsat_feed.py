from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

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


def _follow_reload_page(html: str, base_url: str) -> str | None:
    match = RELOAD_REDIRECT_RE.search(html)
    if match:
        return _normalize_url(match.group("url"), base_url)

    match = META_REFRESH_RE.search(html)
    if match:
        return _normalize_url(match.group("url"), base_url)

    return None


def build_feed_manifest(
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
            stream_urls = extract_stream_urls(detail_html, camera.detail_url)
            if not stream_urls:
                redirect_url = _follow_reload_page(detail_html, camera.detail_url)
                if redirect_url and redirect_url != camera.detail_url:
                    detail_html = fetcher(redirect_url)
                    stream_urls = extract_stream_urls(detail_html, redirect_url)
            camera_payload["stream_urls"] = stream_urls
        except Exception as exc:  # pragma: no cover - exercised in live use
            camera_payload["fetch_error"] = str(exc)
        snapshot_cameras.append(camera_payload)

    return {
        "source_url": index_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "camera_count": len(snapshot_cameras),
        "cameras": snapshot_cameras,
    }


def build_feed_snapshot(
    index_url: str = DEFAULT_INDEX_URL,
    fetcher: Callable[[str], str] = fetch_text,
) -> dict:
    return build_feed_manifest(index_url=index_url, fetcher=fetcher)


def capture_frames_from_manifest(
    manifest: dict,
    output_root: str | Path | None = None,
    frame_count: int = 3,
    ffmpeg_path: list[str] | None = None,
) -> list[dict]:
    output_root = Path(output_root or "frames")
    output_root.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = ffmpeg_path or ["ffmpeg"]

    results = []
    for camera in manifest.get("cameras", []):
        stream_urls = camera.get("stream_urls") or []
        stream_url = next((url for url in stream_urls if str(url).lower().endswith(".m3u8")), None)
        if not stream_url:
            continue

        camera_output_dir = output_root / f"cam_{camera['cam_id']}"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        frame_pattern = str(camera_output_dir / "frame_%03d.jpg")

        command = [*ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error", "-i", stream_url, "-frames:v", str(frame_count), frame_pattern]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        frame_paths = sorted(camera_output_dir.glob("frame_*.jpg"))
        results.append(
            {
                "cam_id": camera["cam_id"],
                "stream_url": stream_url,
                "returncode": completed.returncode,
                "frame_paths": [str(path) for path in frame_paths],
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )

    return results


def capture_frames_loop(
    index_url: str = DEFAULT_INDEX_URL,
    output_root: str | Path = "frames",
    frame_count: int = 3,
    interval_seconds: float = 5.0,
    max_cycles: int | None = None,
    ffmpeg_path: list[str] | None = None,
) -> list[dict]:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    cycle = 0
    all_results = []
    while max_cycles is None or cycle < max_cycles:
        manifest = build_feed_manifest(index_url=index_url)
        results = capture_frames_from_manifest(manifest, output_root=output_root, frame_count=frame_count, ffmpeg_path=ffmpeg_path)
        all_results.extend(results)
        cycle += 1
        if max_cycles is not None and cycle >= max_cycles:
            break
        time.sleep(interval_seconds)

    return all_results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the Macau DSAT realtime traffic camera feed index and resolve live stream URLs."
    )
    parser.add_argument("--index-url", default=DEFAULT_INDEX_URL, help="DSAT realtime index page URL.")
    parser.add_argument("--limit", type=int, default=None, help="Only print the first N cameras.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the JSON output.")
    parser.add_argument("--manifest", action="store_true", help="Write a manifest of discovered cameras and stream URLs.")
    parser.add_argument("--capture-frames", action="store_true", help="Capture frames from the discovered manifest into an output directory.")
    parser.add_argument("--capture-loop", action="store_true", help="Continuously capture frames from the discovered manifest until stopped.")
    parser.add_argument("--output-dir", default="frames", help="Directory for captured frames when --capture-frames or --capture-loop is used.")
    parser.add_argument("--frame-count", type=int, default=3, help="Number of frames to capture per camera when --capture-frames or --capture-loop is used.")
    parser.add_argument("--capture-interval", type=float, default=5.0, help="Delay in seconds between capture cycles when --capture-loop is used.")
    parser.add_argument("--max-cycles", type=int, default=None, help="Maximum number of capture cycles when --capture-loop is used.")
    args = parser.parse_args()

    snapshot = build_feed_snapshot(index_url=args.index_url)
    if args.limit is not None:
        snapshot["cameras"] = snapshot["cameras"][: args.limit]
        snapshot["camera_count"] = len(snapshot["cameras"])

    if args.manifest:
        snapshot = build_feed_manifest(index_url=args.index_url)
        if args.limit is not None:
            snapshot["cameras"] = snapshot["cameras"][: args.limit]
            snapshot["camera_count"] = len(snapshot["cameras"])

    if args.capture_frames:
        manifest = snapshot if args.manifest else build_feed_manifest(index_url=args.index_url)
        if args.limit is not None:
            manifest["cameras"] = manifest["cameras"][: args.limit]
            manifest["camera_count"] = len(manifest["cameras"])
        capture_results = capture_frames_from_manifest(manifest, output_root=args.output_dir, frame_count=args.frame_count)
        snapshot = {"manifest": manifest, "capture_results": capture_results}

    if args.capture_loop:
        capture_results = capture_frames_loop(
            index_url=args.index_url,
            output_root=args.output_dir,
            frame_count=args.frame_count,
            interval_seconds=args.capture_interval,
            max_cycles=args.max_cycles,
        )
        snapshot = {"capture_results": capture_results}

    dump_args = {"ensure_ascii": False}
    if args.pretty:
        dump_args["indent"] = 2
    print(json.dumps(snapshot, **dump_args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
