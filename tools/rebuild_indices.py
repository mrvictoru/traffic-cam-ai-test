"""Backfill per-camera JSONL indices from persisted analysis records."""

from __future__ import annotations

from pathlib import Path

from trafficcam.storage.index import rebuild_camera_index
from trafficcam.storage.json_store import JsonStore


def main() -> int:
    store = JsonStore()
    analyses_root = store.root_dir / "analyses"
    if not analyses_root.exists():
        return 0
    for camera_dir in sorted(path for path in analyses_root.iterdir() if path.is_dir()):
        rebuild_camera_index(store, camera_dir.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())