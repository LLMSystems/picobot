"""AioSQLite-backed persistence for chat token usage events.

Each finished `/chat` or `/chat/stream` call writes one row, so the dashboard's
24h token totals survive process restarts. Replaces the previous Phase 1
in-memory ring (which was wiped on restart).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ChatUsageRow:
    id: int
    ts: str
    session_id: str
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ModelUsageAggregate:
    model: str
    tokens_in: int
    tokens_out: int


@dataclass
class ChatUsageAggregate:
    tokens_in: int = 0
    tokens_out: int = 0
    by_model: list[ModelUsageAggregate] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.by_model is None:
            self.by_model = []


class ChatUsageStore:
    """Persist + query chat token usage events."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError("ChatUsageStore requires 'aiosqlite'.")
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def ensure_schema(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_usage_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        model TEXT,
                        prompt_tokens INTEGER NOT NULL DEFAULT 0,
                        completion_tokens INTEGER NOT NULL DEFAULT 0,
                        total_tokens INTEGER NOT NULL DEFAULT 0
                    )
                    """,
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_usage_ts "
                    "ON chat_usage_events(ts)",
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_chat_usage_session_ts "
                    "ON chat_usage_events(session_id, ts)",
                )
                await conn.commit()
            self._initialized = True

    async def insert(
        self,
        *,
        session_id: str,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        ts: str | None = None,
    ) -> None:
        await self.ensure_schema()
        ts_value = ts or datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO chat_usage_events
                    (ts, session_id, model, prompt_tokens, completion_tokens, total_tokens)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_value,
                    session_id,
                    model,
                    int(prompt_tokens or 0),
                    int(completion_tokens or 0),
                    int(total_tokens or 0),
                ),
            )
            await conn.commit()

    async def aggregate_since(
        self,
        since_iso: str,
        *,
        session_id: str | None = None,
    ) -> ChatUsageAggregate:
        """Sum prompt/completion tokens, plus a per-model breakdown."""
        await self.ensure_schema()
        out = ChatUsageAggregate()
        where = "ts >= ?"
        params: list[object] = [since_iso]
        if session_id is not None:
            where += " AND session_id = ?"
            params.append(session_id)
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                f"""
                SELECT
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM chat_usage_events
                WHERE {where}
                """,
                params,
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                out.tokens_in = int(row[0] or 0)
                out.tokens_out = int(row[1] or 0)

            cursor = await conn.execute(
                f"""
                SELECT
                    COALESCE(model, 'unknown') AS m,
                    COALESCE(SUM(prompt_tokens), 0),
                    COALESCE(SUM(completion_tokens), 0)
                FROM chat_usage_events
                WHERE {where}
                GROUP BY m
                ORDER BY SUM(prompt_tokens) + SUM(completion_tokens) DESC
                """,
                params,
            )
            entries: list[ModelUsageAggregate] = []
            async for model_row in cursor:
                entries.append(
                    ModelUsageAggregate(
                        model=str(model_row[0]),
                        tokens_in=int(model_row[1] or 0),
                        tokens_out=int(model_row[2] or 0),
                    ),
                )
            await cursor.close()
            out.by_model = entries
        return out

    async def list_since(self, since_iso: str) -> list[ChatUsageRow]:
        await self.ensure_schema()
        rows: list[ChatUsageRow] = []
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT id, ts, session_id, model, prompt_tokens,
                       completion_tokens, total_tokens
                FROM chat_usage_events
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since_iso,),
            )
            async for r in cursor:
                rows.append(
                    ChatUsageRow(
                        id=int(r[0]),
                        ts=str(r[1]),
                        session_id=str(r[2]),
                        model=str(r[3]) if r[3] is not None else None,
                        prompt_tokens=int(r[4] or 0),
                        completion_tokens=int(r[5] or 0),
                        total_tokens=int(r[6] or 0),
                    ),
                )
            await cursor.close()
        return rows

    async def prune_older_than(self, *, retention_days: int) -> int:
        await self.ensure_schema()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                "DELETE FROM chat_usage_events WHERE ts < ?",
                (cutoff,),
            )
            await conn.commit()
            count = cursor.rowcount or 0
            await cursor.close()
        return count

    async def row_count(self) -> int:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM chat_usage_events",
            )
            row = await cursor.fetchone()
            await cursor.close()
            return int(row[0]) if row else 0
