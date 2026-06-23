"""Build reusable feed manifests from discovered camera feeds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List

from ..models import CameraFeed


class ManifestBuilder:
    """Create and persist a JSON manifest of discovered feeds."""

    def __init__(self, output_dir: str | Path | None = None) -> None:
        self.output_dir = Path(output_dir or "output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def build_manifest(self, cameras: Iterable[CameraFeed]) -> List[dict]:
        """Convert camera feeds into serializable dictionaries."""
        return [
            {
                "camera_id": camera.camera_id,
                "name": camera.name,
                "detail_url": camera.detail_url,
                "stream_url": camera.stream_url,
                "source": camera.source,
                "metadata": camera.metadata,
            }
            for camera in cameras
        ]

    def save_manifest(self, cameras: Iterable[CameraFeed], manifest_path: str | Path | None = None) -> Path:
        """Persist the manifest to disk."""
        manifest_path = Path(manifest_path or self.output_dir / "manifest.json")
        payload = self.build_manifest(cameras)
        manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return manifest_path
