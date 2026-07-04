from trafficcam.ingestion.dsat_client import DSATClient, extract_camera_entries, extract_stream_urls


def test_extract_camera_entries_handles_relative_and_absolute_links():
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

    assert [camera.cam_id for camera in cameras] == ["49", "50", "51"]
    assert cameras[0].name == "新馬路與南灣大馬路交界"
    assert cameras[1].detail_url == "https://www.dsat.gov.mo/dsat/realtime_core.aspx?lang=en&cam_id=50"


def test_dsat_client_build_manifest_follows_reload_redirects():
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

    client = DSATClient(index_url="https://www.dsat.gov.mo/dsat/realtime.aspx", fetcher=lambda url: responses[url])
    manifest = client.build_manifest()

    assert manifest["camera_count"] == 1
    assert manifest["cameras"][0]["stream_urls"] == ["https://streaming1.dsatmacau.com/traffic/m2181.m3u8"]


def test_extract_camera_entries_captures_district_headers():
    html = """
    <html><body>
      <div class="area_button">澳門區</div>
      <a href="realtime_core.aspx?lang=tc&cam_id=49">新馬路</a>
      <div class="area_button">路氹區</div>
      <a href="realtime_core.aspx?lang=tc&cam_id=51">路氹連貫公路</a>
    </body></html>
    """

    cameras = extract_camera_entries(html, "https://www.dsat.gov.mo/dsat/realtime.aspx")

    assert [c.cam_id for c in cameras] == ["49", "51"]
    assert cameras[0].district == "澳門區"
    assert cameras[1].district == "路氹區"
    assert cameras[0].name == "新馬路"
    assert cameras[1].name == "路氹連貫公路"


def test_build_manifest_includes_district_in_camera_payload():
    responses = {
        "https://www.dsat.gov.mo/dsat/realtime.aspx": """
            <div class="area_button">澳門區</div>
            <a href="realtime_reload.aspx?lang=tc&cam_id=49">新馬路</a>
        """,
        "https://www.dsat.gov.mo/dsat/realtime_reload.aspx?lang=tc&cam_id=49": """
            <a href="realtime_core4.aspx?lang=tc&cam_id=49">Continue</a>
        """,
        "https://www.dsat.gov.mo/dsat/realtime_core4.aspx?lang=tc&cam_id=49": """
            <video src="https://streaming1.dsatmacau.com/traffic/m2181.m3u8"></video>
        """,
    }

    client = DSATClient(
        index_url="https://www.dsat.gov.mo/dsat/realtime.aspx",
        fetcher=lambda url: responses[url],
    )
    manifest = client.build_manifest()

    assert manifest["camera_count"] == 1
    assert manifest["cameras"][0]["district"] == "澳門區"
    assert manifest["cameras"][0]["name"] == "新馬路"
