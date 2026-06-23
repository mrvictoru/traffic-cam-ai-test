"""Ingestion package for discovering and normalizing DSAT camera feeds."""

from .dsat_client import DSATClient
from .manifest_builder import ManifestBuilder

__all__ = ["DSATClient", "ManifestBuilder"]
