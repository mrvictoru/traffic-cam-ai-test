"""Placeholder database backend for future use."""

from __future__ import annotations


class DatabaseStore:
    """A placeholder for a future SQL or SQLite-backed store."""

    def __init__(self, connection_string: str | None = None) -> None:
        self.connection_string = connection_string
