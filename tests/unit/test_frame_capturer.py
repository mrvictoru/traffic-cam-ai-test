import subprocess
import sys
import textwrap
import base64
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from trafficcam.capture.frame_capturer import FrameCapturer
from trafficcam.models import CameraFeed


_JPEG = base64.b64decode(
    " /9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/AP/EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEAAQUCcf/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8BP//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8BP//EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEABj8Cf//Z"
)


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
            data = __import__('base64').b64decode(
                " /9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
                "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/AP/EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEAAQUCcf/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8BP//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8BP//EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEABj8Cf//Z"
            )
            for idx in range(1, frame_count + 1):
                out_path = output_dir / f"frame_{idx:03d}.jpg"
                out_path.write_bytes(data)
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


def test_frame_capturer_clears_stale_frames_before_writing_new_burst(tmp_path: Path):
    manifest = {
        "cameras": [
            {"cam_id": "49", "stream_urls": ["https://example.test/live/49.m3u8"]},
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
            data = __import__('base64').b64decode(
                " /9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
                "2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/AP/EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEAAQUCcf/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8BP//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8BP//EABQQAQAAAAAAAAAAAAAAAAAAACD/2gAIAQEABj8Cf//Z"
            )
            for idx in range(1, frame_count + 1):
                out_path = output_dir / f"frame_{idx:03d}.jpg"
                out_path.write_bytes(data)
            sys.exit(0)
            """
        ).strip()
    )
    fake_ffmpeg.chmod(0o755)

    camera_dir = tmp_path / "frames" / "cam_49"
    camera_dir.mkdir(parents=True, exist_ok=True)
    stale_frame = camera_dir / "frame_003.jpg"
    stale_frame.write_bytes(b"stale")

    capturer = FrameCapturer(output_dir=tmp_path / "frames")
    results = capturer.capture_frames_from_manifest(
        manifest,
        frame_count=2,
        ffmpeg_path=[sys.executable, str(fake_ffmpeg)],
    )

    assert len(results[0]["frame_paths"]) == 2
    assert not stale_frame.exists()


def test_capture_accepts_hls_query_url_and_reports_complete(tmp_path: Path) -> None:
    runner = MagicMock()
    runner.capture_frames.return_value = subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=0, stdout="", stderr=""
    )

    camera_dir = tmp_path / "frames" / "cam_49"
    # The runner mock writes into the requested pattern's parent.
    def write_frames(_url, pattern, frame_count, **_kwargs):
        for idx in range(1, frame_count + 1):
            Path(pattern).parent.mkdir(exist_ok=True)
            Path(pattern).parent.joinpath(f"frame_{idx:03d}.jpg").write_bytes(_JPEG)
        return subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stdout="", stderr="")

    runner.capture_frames.side_effect = write_frames
    result = FrameCapturer(output_dir=tmp_path / "frames", ffmpeg_runner=runner).capture_camera(
        {"cam_id": "49", "stream_urls": ["https://example.test/live.m3u8?token=abc"]},
        frame_count=2,
    )

    assert result["status"] == "complete"
    assert result["stream_url"].endswith("?token=abc")
    assert len(result["frame_paths"]) == 2
    assert runner.capture_frames.call_args.args[0].endswith("?token=abc")


def test_failed_partial_capture_preserves_last_good_frames(tmp_path: Path) -> None:
    output_dir = tmp_path / "frames"
    camera_dir = output_dir / "cam_49"
    camera_dir.mkdir(parents=True)
    old_frame = camera_dir / "frame_001.jpg"
    old_frame.write_bytes(_JPEG)

    runner = MagicMock()
    def write_one(_url, pattern, **_kwargs):
        Path(pattern).parent.mkdir(exist_ok=True)
        Path(pattern).parent.joinpath("frame_001.jpg").write_bytes(_JPEG)
        return subprocess.CompletedProcess(args=["ffmpeg"], returncode=1, stdout="", stderr="broken")
    runner.capture_frames.side_effect = write_one

    result = FrameCapturer(output_dir=output_dir, ffmpeg_runner=runner).capture_camera(
        {"cam_id": "49", "stream_urls": ["https://example.test/live.m3u8"]},
        frame_count=2,
    )

    assert result["status"] == "partial"
    assert result["frame_paths"] == []
    assert old_frame.read_bytes() == _JPEG


def test_legacy_object_capture_does_not_claim_success(tmp_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        FrameCapturer(output_dir=tmp_path).capture(
            [CameraFeed("49", "Camera", "https://example.test/camera")]
        )
