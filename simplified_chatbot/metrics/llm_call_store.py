"""AioSQLite-backed persistence for LLM (provider) call events.

Each call from the agent loop to the LLM provider writes one row, capturing
latency + success/error classification so the dashboard can track LLM
availability and the alert layer can fire on error/timeout/latency regressions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]


# error_type taxonomy: keep it small so dashboards/alerts can reason about it.
ERROR_TYPE_TIMEOUT = "timeout"
ERROR_TYPE_API = "api_error"


@dataclass(frozen=True)
class LlmCallRow:
    id: int
    ts: str
    session_id: str
    model: str | None
    latency_ms: int
    success: bool
    error_type: str | None


@dataclass
class LlmCallAggregate:
    calls: int = 0
    errors: int = 0
    timeouts: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0

    @property
    def error_rate(self) -> float:
        return (self.errors / self.calls) if self.calls else 0.0

    @property
    def timeout_rate(self) -> float:
        return (self.timeouts / self.calls) if self.calls else 0.0


class LlmCallStore:
    """Persist + query LLM call events."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError("LlmCallStore requires 'aiosqlite'.")
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
                    CREATE TABLE IF NOT EXISTS llm_call_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        model TEXT,
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        success INTEGER NOT NULL DEFAULT 1,
                        error_type TEXT
                    )
                    """,
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_call_ts "
                    "ON llm_call_events(ts)",
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_llm_call_session_ts "
                    "ON llm_call_events(session_id, ts)",
                )
                await conn.commit()
            self._initialized = True

    async def insert(
        self,
        *,
        session_id: str,
        model: str | None,
        latency_ms: int,
        success: bool,
        error_type: str | None = None,
        ts: str | None = None,
    ) -> None:
        await self.ensure_schema()
        ts_value = ts or datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO llm_call_events
                    (ts, session_id, model, latency_ms, success, error_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts_value,
                    session_id,
                    model,
                    int(latency_ms or 0),
                    1 if success else 0,
                    error_type,
                ),
            )
            await conn.commit()

    async def aggregate_since(
        self,
        since_iso: str,
        *,
        session_id: str | None = None,
    ) -> LlmCallAggregate:
        """Count calls/errors/timeouts + compute latency p50/p95 since `since_iso`.

        Latency percentiles are computed in Python over the result set; the
        per-hour result sets are small (one row per LLM call), so this is
        cheap enough not to warrant SQL window-function gymnastics.
        """
        await self.ensure_schema()
        where = "ts >= ?"
        params: list[object] = [since_iso]
        if session_id is not None:
            where += " AND session_id = ?"
            params.append(session_id)

        out = LlmCallAggregate()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                f"""
                SELECT
                    COUNT(*) AS calls,
                    COALESCE(SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END), 0) AS errors,
                    COALESCE(SUM(CASE WHEN error_type = ? THEN 1 ELSE 0 END), 0) AS timeouts
                FROM llm_call_events
                WHERE {where}
                """,
                [ERROR_TYPE_TIMEOUT, *params],
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is not None:
                out.calls = int(row[0] or 0)
                out.errors = int(row[1] or 0)
                out.timeouts = int(row[2] or 0)

            if out.calls > 0:
                cursor = await conn.execute(
                    f"""
                    SELECT latency_ms
                    FROM llm_call_events
                    WHERE {where}
                    ORDER BY latency_ms ASC
                    """,
                    params,
                )
                latencies = [int(r[0] or 0) async for r in cursor]
                await cursor.close()
                out.latency_p50_ms = _percentile(latencies, 50)
                out.latency_p95_ms = _percentile(latencies, 95)

        return out

    async def list_since(self, since_iso: str) -> list[LlmCallRow]:
        await self.ensure_schema()
        rows: list[LlmCallRow] = []
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT id, ts, session_id, model, latency_ms, success, error_type
                FROM llm_call_events
                WHERE ts >= ?
                ORDER BY ts ASC
                """,
                (since_iso,),
            )
            async for r in cursor:
                rows.append(
                    LlmCallRow(
                        id=int(r[0]),
                        ts=str(r[1]),
                        session_id=str(r[2]),
                        model=str(r[3]) if r[3] is not None else None,
                        latency_ms=int(r[4] or 0),
                        success=bool(r[5]),
                        error_type=str(r[6]) if r[6] is not None else None,
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
                "DELETE FROM llm_call_events WHERE ts < ?",
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
                "SELECT COUNT(*) FROM llm_call_events",
            )
            row = await cursor.fetchone()
            await cursor.close()
            return int(row[0]) if row else 0


def _percentile(sorted_values: list[int], pct: float) -> float:
    """Linear-interp percentile over an already-sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return float(sorted_values[f])
    d0 = sorted_values[f] * (c - k)
    d1 = sorted_values[c] * (k - f)
    return float(d0 + d1)
