"""Capture package for frame extraction from live feeds."""

from .frame_capturer import FrameCapturer
from .ffmpeg_runner import FFmpegRunner

__all__ = ["FrameCapturer", "FFmpegRunner"]
