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

    def append_jsonl(self, path: str | Path, payload: Any) -> None:
        """Append one JSON object per line to a JSONL file."""
        target = self.root_dir / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")

    def load_jsonl(self, path: str | Path) -> list[Any]:
        """Load all objects from a newline-delimited JSON file."""
        target = self.root_dir / Path(path)
        if not target.exists():
            raise FileNotFoundError(target)
        with target.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def save_jsonl(self, path: str | Path, payloads: list[Any]) -> None:
        """Write a complete newline-delimited JSON file."""
        target = self.root_dir / Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload, separators=(",", ":")) + "\n")

    def list_records(self, prefix: str = "") -> Iterable[str]:
        """List JSON record paths under the storage root."""
        if not self.root_dir.exists():
            return []
        prefix_value = prefix.replace("\\", "/")
        results = []
        for path in self.root_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root_dir).as_posix()
            if prefix_value and not relative.startswith(prefix_value):
                continue
            results.append(relative)
        return sorted(results)
