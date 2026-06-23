import subprocess
from pathlib import Path

from trafficcam.ingestion.dsat_client import DSATClient


def test_extracts_live_frames_from_two_different_feeds():
    output_dir = Path(__file__).resolve().parent.parent / "output" / "live_feed_frames"
    output_dir.mkdir(parents=True, exist_ok=True)

    client = DSATClient()
    manifest = client.build_manifest(limit=2)
    cameras = manifest["cameras"]

    assert len(cameras) >= 2

    selected = []
    for camera in cameras:
        stream_urls = camera.get("stream_urls") or []
        stream_url = next((url for url in stream_urls if url.lower().endswith(".m3u8")), None)
        if stream_url:
            selected.append((camera["cam_id"], stream_url))
        if len(selected) >= 2:
            break

    assert len(selected) >= 2

    for cam_id, stream_url in selected[:2]:
        camera_output_dir = output_dir / f"cam_{cam_id}"
        camera_output_dir.mkdir(parents=True, exist_ok=True)
        frame_pattern = str(camera_output_dir / "frame_%03d.jpg")

        result = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", stream_url, "-frames:v", "3", frame_pattern],
            capture_output=True,
            text=True,
            timeout=180,
        )

        assert result.returncode == 0, result.stderr or result.stdout
        frame_paths = sorted(camera_output_dir.glob("frame_*.jpg"))
        assert len(frame_paths) >= 3
