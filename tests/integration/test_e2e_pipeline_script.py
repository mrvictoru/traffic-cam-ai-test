import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_e2e_pipeline import run_pipeline


def test_run_pipeline_persists_analysis_and_incidents(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_url": "https://example.test/index",
                "camera_count": 1,
                "cameras": [
                    {
                        "cam_id": "1001",
                        "name": "Test Camera",
                        "detail_url": "https://example.test/cam/1001",
                        "stream_urls": ["https://example.test/stream.m3u8"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = run_pipeline(
        manifest_file=manifest_path,
        output_dir=tmp_path / "output",
        data_dir=tmp_path / "data",
        frame_count=1,
        limit=1,
    )

    assert result["analysis_count"] >= 1
    assert result["camera_ids"] == ["1001"]
    assert (tmp_path / "data" / "analyses" / "1001").exists()
