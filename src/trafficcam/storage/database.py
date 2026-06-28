"""Simple SQLite-backed store for lightweight persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class DatabaseStore:
    """Persist small JSON-like records into a local SQLite database."""

    def __init__(self, connection_string: str | None = None) -> None:
        self.connection_string = connection_string or "trafficcam.sqlite3"
        self._ensure_database()

    def _ensure_database(self) -> None:
        path = Path(self.connection_string)
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.connection_string) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS records (collection TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save_records(self, collection: str, records: list[dict[str, Any]]) -> None:
        """Store records in a collection table."""
        with sqlite3.connect(self.connection_string) as connection:
            connection.execute("DELETE FROM records WHERE collection = ?", (collection,))
            for record in records:
                connection.execute(
                    "INSERT INTO records(collection, payload) VALUES (?, ?)",
                    (collection, json.dumps(record)),
                )

    def load_records(self, collection: str) -> list[dict[str, Any]]:
        """Load all records from a given collection."""
        with sqlite3.connect(self.connection_string) as connection:
            rows = connection.execute(
                "SELECT payload FROM records WHERE collection = ? ORDER BY rowid", (collection,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]
