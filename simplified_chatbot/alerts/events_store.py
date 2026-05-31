"""AioSQLite-backed persistence for alert events + per-rule silences.

`alert_events` is append-only: each firing instance becomes one row, and
resolution / acknowledgement are recorded by updating `resolved_at` /
`acknowledged_at` on the same row.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]


@dataclass
class AlertEventRow:
    id: int
    rule_name: str
    severity: str
    description: str
    metric_path: str
    comparator: str
    threshold: str  # stored as text since it may be a bool
    fired_at: str
    resolved_at: str | None
    acknowledged_at: str | None
    trigger_value: float | None
    context: dict[str, Any]


class AlertEventsStore:
    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "AlertEventsStore requires 'aiosqlite'.",
            )
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
                    CREATE TABLE IF NOT EXISTS alert_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        rule_name TEXT NOT NULL,
                        severity TEXT NOT NULL,
                        description TEXT NOT NULL,
                        metric_path TEXT NOT NULL,
                        comparator TEXT NOT NULL,
                        threshold TEXT NOT NULL,
                        fired_at TEXT NOT NULL,
                        resolved_at TEXT,
                        acknowledged_at TEXT,
                        trigger_value REAL,
                        context_json TEXT NOT NULL DEFAULT '{}'
                    )
                    """,
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alert_events_fired_at "
                    "ON alert_events(fired_at)",
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_alert_events_rule "
                    "ON alert_events(rule_name, fired_at DESC)",
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alert_silences (
                        rule_name TEXT PRIMARY KEY,
                        silenced_until TEXT NOT NULL,
                        silenced_at TEXT NOT NULL
                    )
                    """,
                )
                await conn.commit()
            self._initialized = True

    async def insert_firing(
        self,
        *,
        rule_name: str,
        severity: str,
        description: str,
        metric_path: str,
        comparator: str,
        threshold: Any,
        fired_at: str,
        trigger_value: float | None,
        context: dict[str, Any],
    ) -> int:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO alert_events
                    (rule_name, severity, description, metric_path, comparator,
                     threshold, fired_at, trigger_value, context_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_name,
                    severity,
                    description,
                    metric_path,
                    comparator,
                    str(threshold),
                    fired_at,
                    trigger_value,
                    json.dumps(context, ensure_ascii=False),
                ),
            )
            await conn.commit()
            new_id = cursor.lastrowid
            await cursor.close()
        return int(new_id or 0)

    async def mark_resolved(self, *, event_id: int, resolved_at: str) -> None:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                UPDATE alert_events
                SET resolved_at = ?
                WHERE id = ? AND resolved_at IS NULL
                """,
                (resolved_at, event_id),
            )
            await conn.commit()

    async def mark_acknowledged(self, *, event_id: int, acked_at: str) -> bool:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = ?
                WHERE id = ? AND acknowledged_at IS NULL
                """,
                (acked_at, event_id),
            )
            await conn.commit()
            ok = cursor.rowcount > 0
            await cursor.close()
        return ok

    async def list_active(self) -> list[AlertEventRow]:
        """Return events with resolved_at IS NULL — i.e. currently firing."""
        await self.ensure_schema()
        rows: list[AlertEventRow] = []
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT id, rule_name, severity, description, metric_path,
                       comparator, threshold, fired_at, resolved_at,
                       acknowledged_at, trigger_value, context_json
                FROM alert_events
                WHERE resolved_at IS NULL
                ORDER BY fired_at DESC
                """,
            )
            async for row in cursor:
                rows.append(_row_from_tuple(row))
            await cursor.close()
        return rows

    async def list_history(self, *, limit: int = 100) -> list[AlertEventRow]:
        """Return the most recent N events regardless of state."""
        await self.ensure_schema()
        rows: list[AlertEventRow] = []
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT id, rule_name, severity, description, metric_path,
                       comparator, threshold, fired_at, resolved_at,
                       acknowledged_at, trigger_value, context_json
                FROM alert_events
                ORDER BY fired_at DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            async for row in cursor:
                rows.append(_row_from_tuple(row))
            await cursor.close()
        return rows

    async def prune_older_than(self, *, retention_days: int) -> int:
        await self.ensure_schema()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                "DELETE FROM alert_events WHERE fired_at < ? AND resolved_at IS NOT NULL",
                (cutoff,),
            )
            await conn.commit()
            count = cursor.rowcount or 0
            await cursor.close()
        return count

    # ---- silences -----------------------------------------------------------

    async def set_silence(self, *, rule_name: str, silenced_until: str) -> None:
        await self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                """
                INSERT INTO alert_silences (rule_name, silenced_until, silenced_at)
                VALUES (?, ?, ?)
                ON CONFLICT(rule_name) DO UPDATE SET
                    silenced_until = excluded.silenced_until,
                    silenced_at = excluded.silenced_at
                """,
                (rule_name, silenced_until, now),
            )
            await conn.commit()

    async def clear_silence(self, *, rule_name: str) -> None:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                "DELETE FROM alert_silences WHERE rule_name = ?",
                (rule_name,),
            )
            await conn.commit()

    async def active_silences(self) -> dict[str, str]:
        """Return {rule_name: silenced_until_iso} for silences not yet expired."""
        await self.ensure_schema()
        now = datetime.now(timezone.utc).isoformat()
        out: dict[str, str] = {}
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                "SELECT rule_name, silenced_until FROM alert_silences "
                "WHERE silenced_until > ?",
                (now,),
            )
            async for row in cursor:
                out[str(row[0])] = str(row[1])
            await cursor.close()
        return out


def _row_from_tuple(row: tuple) -> AlertEventRow:
    (
        ev_id, rule_name, severity, description, metric_path, comparator,
        threshold, fired_at, resolved_at, acknowledged_at, trigger_value,
        context_json,
    ) = row
    try:
        ctx = json.loads(context_json) if context_json else {}
    except Exception:
        ctx = {}
    return AlertEventRow(
        id=int(ev_id),
        rule_name=str(rule_name),
        severity=str(severity),
        description=str(description),
        metric_path=str(metric_path),
        comparator=str(comparator),
        threshold=str(threshold),
        fired_at=str(fired_at),
        resolved_at=str(resolved_at) if resolved_at else None,
        acknowledged_at=str(acknowledged_at) if acknowledged_at else None,
        trigger_value=float(trigger_value) if trigger_value is not None else None,
        context=ctx if isinstance(ctx, dict) else {},
    )
