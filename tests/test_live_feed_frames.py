import subprocess
import unittest
from pathlib import Path

from macau_dsat_feed import DEFAULT_INDEX_URL, extract_camera_entries, extract_stream_urls, fetch_text


class LiveFeedFrameExtractionTests(unittest.TestCase):
    def test_extracts_live_frames_from_two_different_feeds(self) -> None:
        output_dir = Path(__file__).resolve().parent / "output" / "live_feed_frames"
        output_dir.mkdir(parents=True, exist_ok=True)

        index_html = fetch_text(DEFAULT_INDEX_URL)
        cameras = extract_camera_entries(index_html, DEFAULT_INDEX_URL)

        self.assertGreaterEqual(len(cameras), 2, "Expected at least two cameras from the live index page")

        selected_cameras = []
        for camera in cameras[:2]:
            detail_html = fetch_text(camera.detail_url)
            stream_urls = extract_stream_urls(detail_html, camera.detail_url)
            stream_url = next((url for url in stream_urls if url.lower().endswith(".m3u8")), None)
            if stream_url:
                selected_cameras.append((camera.cam_id, stream_url))
            if len(selected_cameras) >= 2:
                break

        self.assertGreaterEqual(len(selected_cameras), 2, "Expected at least two HLS stream URLs")

        for cam_id, stream_url in selected_cameras[:2]:
            camera_output_dir = output_dir / f"cam_{cam_id}"
            camera_output_dir.mkdir(parents=True, exist_ok=True)
            frame_pattern = str(camera_output_dir / "frame_%03d.jpg")

            result = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", stream_url, "-frames:v", "3", frame_pattern],
                capture_output=True,
                text=True,
                timeout=180,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            frame_paths = sorted(camera_output_dir.glob("frame_*.jpg"))
            self.assertGreaterEqual(len(frame_paths), 3, f"Expected at least three frame files for camera {cam_id}")
            for frame_path in frame_paths:
                self.assertGreater(frame_path.stat().st_size, 0, f"Frame file is empty: {frame_path}")


if __name__ == "__main__":
    unittest.main()
