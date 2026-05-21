"""Durable SQLite snapshot store for local RAG metadata."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteRagStateStore:
    """Persist local RAG state in SQLite so managed KBs survive restarts.

    The first production slice stores a versioned JSON snapshot in SQLite. This
    keeps the service restart-safe without prematurely committing to the final
    normalized schema that external vector stores may require.
    """

    SNAPSHOT_KEY = "rag_state"

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def load(self) -> dict[str, Any] | None:
        """Load the latest persisted RAG snapshot, if present."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM rag_state WHERE key = ?",
                (self.SNAPSHOT_KEY,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        return payload if isinstance(payload, dict) else None

    def save(self, payload: dict[str, Any]) -> None:
        """Persist a complete RAG snapshot atomically."""
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rag_state(key, value, updated_at)
                VALUES(?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (self.SNAPSHOT_KEY, serialized),
            )

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
