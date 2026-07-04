"""Abstract storage interface for persisted pipeline artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Iterable


class StorageBackend(ABC):
    """Base class for simple storage backends."""

    @abstractmethod
    def save_json(self, path: str | Path, payload: Any) -> None:
        """Persist arbitrary JSON-serializable data."""

    @abstractmethod
    def load_json(self, path: str | Path) -> Any:
        """Load JSON-serializable data from disk."""

    @abstractmethod
    def append_jsonl(self, path: str | Path, payload: Any) -> None:
        """Append a JSON-serializable object as one line of JSON."""

    @abstractmethod
    def load_jsonl(self, path: str | Path) -> list[Any]:
        """Load newline-delimited JSON objects from disk."""

    @abstractmethod
    def save_jsonl(self, path: str | Path, payloads: list[Any]) -> None:
        """Write newline-delimited JSON objects to disk."""

    @abstractmethod
    def list_records(self, prefix: str = "") -> Iterable[str]:
        """List persisted artifact paths."""
