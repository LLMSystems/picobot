"""SQLite database size and row count samples."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.runtime.sqlite_pragmas import open_async


_KNOWN_TABLES = (
    "session_messages",
    "session_metadata",
    "subagent_runs",
    "subagent_events",
)


@dataclass
class SqliteSample:
    db_file_bytes: int | None
    row_counts: dict[str, int] = field(default_factory=dict)


class SqliteStatsCollector:
    """Sample DB file size and a fixed set of table row counts."""

    def __init__(self, db_path: str | Path | None) -> None:
        self._db_path = Path(db_path).expanduser().resolve() if db_path else None

    async def collect(self) -> SqliteSample:
        if self._db_path is None or aiosqlite is None or not self._db_path.exists():
            return SqliteSample(db_file_bytes=None, row_counts={})
        try:
            size = self._db_path.stat().st_size
        except OSError:
            size = None
        row_counts: dict[str, int] = {}
        try:
            async with open_async(self._db_path) as conn:
                for table in _KNOWN_TABLES:
                    try:
                        cursor = await conn.execute(
                            f"SELECT COUNT(*) FROM {table}",  # noqa: S608 - fixed names
                        )
                        row = await cursor.fetchone()
                        await cursor.close()
                        if row is not None:
                            row_counts[table] = int(row[0])
                    except Exception:
                        # Table doesn't exist yet; skip silently.
                        continue
        except Exception:
            pass
        return SqliteSample(db_file_bytes=size, row_counts=row_counts)
