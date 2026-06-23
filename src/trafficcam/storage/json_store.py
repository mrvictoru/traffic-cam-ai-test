"""Simple file-based JSON storage backend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .base import StorageBackend


class JsonStore(StorageBackend):
    """Persist JSON data in a local directory."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self.root_dir = Path(root_dir or "data")
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, path: str | Path, payload: Any) -> None:
        """Write a JSON payload to disk."""
        target = self.root_dir / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_json(self, path: str | Path) -> Any:
        """Load a JSON payload from disk."""
        target = self.root_dir / Path(path)
        return json.loads(target.read_text(encoding="utf-8"))

    def list_records(self, prefix: str = "") -> Iterable[str]:
        """List JSON record paths under the storage root."""
        if not self.root_dir.exists():
            return []
        return [str(path.relative_to(self.root_dir)) for path in self.root_dir.rglob("*.json") if prefix in str(path)]
