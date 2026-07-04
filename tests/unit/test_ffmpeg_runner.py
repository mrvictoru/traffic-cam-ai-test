from pathlib import Path
from unittest.mock import patch

from trafficcam.capture.ffmpeg_runner import FFmpegRunner


def test_capture_frames_uses_spacing_filter_for_multi_frame_bursts(tmp_path: Path) -> None:
    runner = FFmpegRunner(ffmpeg_path="ffmpeg")
    output_pattern = tmp_path / "frame_%03d.jpg"

    with patch("subprocess.run") as run_mock:
        runner.capture_frames(
            "https://example.test/stream.m3u8",
            output_pattern,
            frame_count=3,
            sample_fps=1.0,
            warmup_seconds=0.5,
        )

    command = run_mock.call_args.args[0]
    assert "-ss" in command
    assert "0.5" in command
    assert "-vf" in command
    assert "fps=1" in command
    assert command[-2:] == ["3", str(output_pattern)]


def test_capture_frames_skips_spacing_filter_for_single_frame(tmp_path: Path) -> None:
    runner = FFmpegRunner(ffmpeg_path="ffmpeg")
    output_path = tmp_path / "frame_001.jpg"

    with patch("subprocess.run") as run_mock:
        runner.capture_frames(
            "https://example.test/stream.m3u8",
            output_path,
            frame_count=1,
            sample_fps=1.0,
        )

    command = run_mock.call_args.args[0]
    assert "-vf" not in command