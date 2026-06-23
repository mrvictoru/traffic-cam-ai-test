import subprocess
import sys
import textwrap
from pathlib import Path

from trafficcam.capture.frame_capturer import FrameCapturer


def test_frame_capturer_writes_expected_output_files(tmp_path: Path):
    manifest = {
        "cameras": [
            {"cam_id": "49", "stream_urls": ["https://example.test/live/49.m3u8"]},
            {"cam_id": "50", "stream_urls": ["https://example.test/live/50.m3u8"]},
        ]
    }

    fake_ffmpeg = tmp_path / "fake_ffmpeg.py"
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

    capturer = FrameCapturer(output_dir=tmp_path / "frames")
    results = capturer.capture_frames_from_manifest(
        manifest,
        frame_count=2,
        ffmpeg_path=[sys.executable, str(fake_ffmpeg)],
    )

    assert len(results) == 2
    assert (tmp_path / "frames" / "cam_49" / "frame_001.jpg").exists()
    assert (tmp_path / "frames" / "cam_50" / "frame_002.jpg").exists()
