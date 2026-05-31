"""Session-count aggregators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.runtime.sqlite_pragmas import open_async


@dataclass
class SessionStats:
    total_sessions: int
    active_24h: int
    new_24h: int


async def aggregate_sessions(db_path: str | Path | None) -> SessionStats:
    if db_path is None or aiosqlite is None:
        return SessionStats(total_sessions=0, active_24h=0, new_24h=0)
    p = Path(db_path)
    if not p.exists():
        return SessionStats(total_sessions=0, active_24h=0, new_24h=0)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    async with open_async(p) as conn:
        total = await _scalar(conn, "SELECT COUNT(*) FROM session_metadata")
        active = await _scalar(
            conn,
            "SELECT COUNT(*) FROM session_metadata WHERE updated_at >= ?",
            (cutoff,),
        )
        new = await _scalar(
            conn,
            "SELECT COUNT(*) FROM session_metadata WHERE created_at >= ?",
            (cutoff,),
        )
    return SessionStats(
        total_sessions=total,
        active_24h=active,
        new_24h=new,
    )


async def list_active_session_ids(
    db_path: str | Path | None,
    *,
    lookback_hours: int = 24,
    limit: int = 100,
) -> list[str]:
    """Return session ids with recent activity, newest first."""
    if db_path is None or aiosqlite is None:
        return []
    p = Path(db_path)
    if not p.exists():
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    try:
        async with open_async(p) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id
                FROM session_metadata
                WHERE updated_at >= ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (cutoff, limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()
    except Exception:
        # DB file exists (e.g. another store created it) but session_metadata
        # hasn't been initialised yet — treat as no sessions.
        return []
    return [str(row[0]) for row in rows]


async def _scalar(
    conn: "aiosqlite.Connection",
    sql: str,
    params: Sequence[object] = (),
) -> int:
    try:
        cursor = await conn.execute(sql, params)
        row = await cursor.fetchone()
        await cursor.close()
        return int(row[0]) if row is not None else 0
    except Exception:
        return 0
