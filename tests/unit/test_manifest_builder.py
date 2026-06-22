from pathlib import Path

from trafficcam.ingestion.manifest_builder import ManifestBuilder
from trafficcam.models import CameraFeed


def test_manifest_builder_saves_json(tmp_path: Path):
    builder = ManifestBuilder(output_dir=tmp_path)
    cameras = [CameraFeed(camera_id="cam-1", name="Camera 1", detail_url="https://example.test")]
    manifest_path = builder.save_manifest(cameras)
    assert manifest_path.exists()
    payload = manifest_path.read_text(encoding="utf-8")
    assert "cam-1" in payload
