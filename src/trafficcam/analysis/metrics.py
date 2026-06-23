"""Basic metrics helpers for aggregate analysis results."""

from __future__ import annotations

from typing import Iterable


def average_confidence(results: Iterable[dict]) -> float:
    """Compute the average confidence from a sequence of analysis results."""
    values = [float(result.get("confidence", 0.0)) for result in results]
    if not values:
        return 0.0
    return sum(values) / len(values)
