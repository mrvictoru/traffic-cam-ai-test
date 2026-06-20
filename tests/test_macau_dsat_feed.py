import unittest

from macau_dsat_feed import build_feed_snapshot, extract_camera_entries, extract_stream_urls


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


if __name__ == "__main__":
    unittest.main()
