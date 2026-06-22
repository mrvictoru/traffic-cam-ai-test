import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from macau_dsat_feed import (
    build_feed_manifest,
    build_feed_snapshot,
    capture_frames_from_manifest,
    extract_camera_entries,
    extract_stream_urls,
)


class ExtractCameraEntriesTests(unittest.TestCase):
    def test_extracts_camera_links_and_deduplicates_cam_ids(self) -> None:
        html = """
        <html><body>
          <a href="realtime_core.aspx?lang=zh_tw&cam_id=49">新馬路與南灣大馬路交界</a>
          <a href="/dsat/realtime_core.aspx?lang=en&cam_id=50">水坑尾街與南灣大馬路交界路口</a>
          <script>
            var fallback = "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=49";
            var anonymousCamera = "realtime_core.aspx?lang=en&cam_id=51";
          </script>
        </body></html>
        """

        cameras = extract_camera_entries(html, "https://www.dsat.gov.mo/dsat/realtime.aspx")

        self.assertEqual(["49", "50", "51"], [camera.cam_id for camera in cameras])
        self.assertEqual("新馬路與南灣大馬路交界", cameras[0].name)
        self.assertEqual(
            "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=50",
            cameras[1].detail_url,
        )
        self.assertIsNone(cameras[2].name)


class ExtractStreamUrlsTests(unittest.TestCase):
    def test_extracts_m3u8_images_and_relative_snapshots(self) -> None:
        html = """
        <html><body>
          <video src="https://streaming1.dsatmacau.com/traffic/m2181.m3u8"></video>
          <img src="/dsat/image.aspx?src=49&t=1718800000" />
          <img src="/traffic/snapshots/cam49.jpg?ts=1718800000" />
        </body></html>
        """

        urls = extract_stream_urls(html, "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=49")

        self.assertEqual(
            [
                "https://streaming1.dsatmacau.com/traffic/m2181.m3u8",
                "https://www.dsat.gov.mo/dsat/image.aspx?src=49&t=1718800000",
                "https://www.dsat.gov.mo/traffic/snapshots/cam49.jpg?ts=1718800000",
            ],
            urls,
        )


class BuildFeedSnapshotTests(unittest.TestCase):
    def test_builds_snapshot_from_index_and_detail_pages(self) -> None:
        responses = {
            "https://www.dsat.gov.mo/dsat/realtime.aspx": """
                <a href="realtime_core.aspx?lang=en&cam_id=49">新馬路與南灣大馬路交界</a>
                <a href="realtime_core.aspx?lang=en&cam_id=50">水坑尾街與南灣大馬路交界路口</a>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=49": """
                <video src="https://streaming1.dsatmacau.com/traffic/m2181.m3u8"></video>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=50": """
                <img src="/dsat/image.aspx?src=50&t=1718800001" />
            """,
        }

        snapshot = build_feed_snapshot(
            fetcher=lambda url: responses[url],
        )

        self.assertEqual(2, snapshot["camera_count"])
        self.assertEqual("49", snapshot["cameras"][0]["cam_id"])
        self.assertEqual(
            ["https://streaming1.dsatmacau.com/traffic/m2181.m3u8"],
            snapshot["cameras"][0]["stream_urls"],
        )
        self.assertEqual(
            ["https://www.dsat.gov.mo/dsat/image.aspx?src=50&t=1718800001"],
            snapshot["cameras"][1]["stream_urls"],
        )


class FeedManifestTests(unittest.TestCase):
    def test_builds_manifest_with_stream_urls(self) -> None:
        responses = {
            "https://www.dsat.gov.mo/dsat/realtime.aspx": """
                <a href="realtime_core4.aspx?lang=en&cam_id=49">Camera 49</a>
                <a href="realtime_core4.aspx?lang=en&cam_id=50">Camera 50</a>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_core4.aspx?lang=en&cam_id=49": """
                <video src="https://streaming1.dsatmacau.com/traffic/m2181.m3u8"></video>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_core4.aspx?lang=en&cam_id=50": """
                <img src="/dsat/image.aspx?src=50&t=1718800001" />
            """,
        }

        manifest = build_feed_manifest(fetcher=lambda url: responses[url], index_url="https://www.dsat.gov.mo/dsat/realtime.aspx")

        self.assertEqual(2, manifest["camera_count"])
        self.assertEqual("49", manifest["cameras"][0]["cam_id"])
        self.assertEqual(["https://streaming1.dsatmacau.com/traffic/m2181.m3u8"], manifest["cameras"][0]["stream_urls"])

    def test_follows_reload_page_to_real_detail(self) -> None:
        responses = {
            "https://www.dsat.gov.mo/dsat/realtime.aspx": """
                <a href="realtime_reload.aspx?lang=en&cam_id=49">Camera 49</a>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_reload.aspx?lang=en&cam_id=49": """
                <a href="realtime_core4.aspx?lang=en&cam_id=49">Continue</a>
            """,
            "https://www.dsat.gov.mo/dsat/realtime_core4.aspx?lang=en&cam_id=49": """
                <video src="https://streaming1.dsatmacau.com/traffic/m2181.m3u8"></video>
            """,
        }

        manifest = build_feed_manifest(fetcher=lambda url: responses[url], index_url="https://www.dsat.gov.mo/dsat/realtime.aspx")

        self.assertEqual(1, manifest["camera_count"])
        self.assertEqual(["https://streaming1.dsatmacau.com/traffic/m2181.m3u8"], manifest["cameras"][0]["stream_urls"])


class CaptureFramesTests(unittest.TestCase):
    def test_capture_frames_writes_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "frames"
            manifest = {
                "cameras": [
                    {"cam_id": "49", "stream_urls": ["https://example.test/live/49.m3u8"]},
                    {"cam_id": "50", "stream_urls": ["https://example.test/live/50.m3u8"]},
                ]
            }

            fake_ffmpeg = Path(tmpdir) / "fake_ffmpeg.py"
            fake_ffmpeg.write_text(
                textwrap.dedent(
                    """
                    import pathlib
                    import sys

                    args = sys.argv[1:]
                    frame_count = int(args[args.index('-frames:v') + 1])
                    pattern = args[-1]
                    output_dir = pathlib.Path(pattern).parent
                    output_dir.mkdir(parents=True, exist_ok=True)
                    for idx in range(1, frame_count + 1):
                        out_path = output_dir / f"frame_{idx:03d}.jpg"
                        out_path.write_bytes(b"fake-image")
                    sys.exit(0)
                    """
                ).strip()
            )
            fake_ffmpeg.chmod(0o755)

            results = capture_frames_from_manifest(
                manifest,
                output_root=output_root,
                frame_count=2,
                ffmpeg_path=[sys.executable, str(fake_ffmpeg)],
            )

            self.assertEqual(2, len(results))
            self.assertTrue((output_root / "cam_49" / "frame_001.jpg").exists())
            self.assertTrue((output_root / "cam_50" / "frame_002.jpg").exists())


if __name__ == "__main__":
    unittest.main()
