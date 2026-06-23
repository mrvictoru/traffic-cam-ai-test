"""Retry policy helpers for flaky or slow capture tasks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetryPolicy:
    """Minimal retry guidance for capture workflows."""

    max_attempts: int = 3
    delay_seconds: float = 1.0
