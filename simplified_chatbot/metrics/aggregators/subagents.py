"""Subagent statistics aggregator."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.metrics.recorders import percentile


@dataclass
class SubagentStats:
    runs_24h: int = 0
    success_rate_24h: float = 1.0
    duration_p50_ms: float = 0.0
    duration_p95_ms: float = 0.0
    running_now: int = 0
    longest_running_seconds: float = 0.0  # longest currently-running subagent age
    tokens_in_24h: int = 0
    tokens_out_24h: int = 0


@dataclass
class SubagentSessionStats:
    runs_total: int = 0
    success_total: int = 0
    failure_total: int = 0
    tokens_in_total: int = 0
    tokens_out_total: int = 0
    tokens_by_model: dict[str, dict[str, int]] = field(default_factory=dict)


async def aggregate_subagents(db_path: str | Path | None) -> SubagentStats:
    out = SubagentStats()
    rows = await _load_subagent_rows(db_path, since_iso=_iso_24h_ago())
    if not rows:
        running = await _count_running(db_path)
        out.running_now = running
        out.longest_running_seconds = await _longest_running_seconds(db_path)
        return out

    durations: list[float] = []
    success = 0
    failure = 0
    for row in rows:
        if row.duration_ms is not None:
            durations.append(row.duration_ms)
        if row.phase == "done" and (row.ok is None or row.ok):
            success += 1
        elif row.phase in {"failed", "cancelled"} or row.ok is False:
            failure += 1
        out.tokens_in_24h += row.tokens_in
        out.tokens_out_24h += row.tokens_out

    out.runs_24h = len(rows)
    seen = success + failure
    out.success_rate_24h = success / seen if seen > 0 else 1.0
    out.duration_p50_ms = percentile(durations, 0.5)
    out.duration_p95_ms = percentile(durations, 0.95)
    out.running_now = await _count_running(db_path)
    out.longest_running_seconds = await _longest_running_seconds(db_path)
    return out


async def aggregate_subagents_for_session(
    db_path: str | Path | None,
    session_id: str,
) -> SubagentSessionStats:
    out = SubagentSessionStats()
    rows = await _load_subagent_rows(
        db_path,
        parent_session_id=session_id,
    )
    for row in rows:
        out.runs_total += 1
        if row.phase == "done" and (row.ok is None or row.ok):
            out.success_total += 1
        elif row.phase in {"failed", "cancelled"} or row.ok is False:
            out.failure_total += 1
        out.tokens_in_total += row.tokens_in
        out.tokens_out_total += row.tokens_out
        if row.model:
            bucket = out.tokens_by_model.setdefault(
                row.model,
                {"tokens_in": 0, "tokens_out": 0},
            )
            bucket["tokens_in"] += row.tokens_in
            bucket["tokens_out"] += row.tokens_out
    return out


@dataclass
class _SubagentRow:
    phase: str
    ok: bool | None
    duration_ms: float | None
    tokens_in: int
    tokens_out: int
    model: str | None


async def _load_subagent_rows(
    db_path: str | Path | None,
    *,
    since_iso: str | None = None,
    parent_session_id: str | None = None,
) -> list[_SubagentRow]:
    if db_path is None or aiosqlite is None:
        return []
    p = Path(db_path)
    if not p.exists():
        return []
    where: list[str] = []
    params: list[object] = []
    if since_iso is not None:
        where.append("started_at >= ?")
        params.append(since_iso)
    if parent_session_id is not None:
        where.append("parent_session_id = ?")
        params.append(parent_session_id)
    sql = (
        "SELECT phase, ok, started_at, finished_at, usage_json, model "
        "FROM subagent_runs"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    out: list[_SubagentRow] = []
    try:
        async with aiosqlite.connect(str(p)) as conn:
            cursor = await conn.execute(sql, params)
            async for row in cursor:
                phase, ok_raw, started_at, finished_at, usage_json, model = row
                tokens_in, tokens_out = _split_usage(usage_json)
                duration_ms = _duration_ms(started_at, finished_at)
                out.append(
                    _SubagentRow(
                        phase=str(phase) if phase is not None else "unknown",
                        ok=_coerce_ok(ok_raw),
                        duration_ms=duration_ms,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        model=str(model) if model is not None else None,
                    ),
                )
            await cursor.close()
    except Exception:
        return out
    return out


async def _longest_running_seconds(db_path: str | Path | None) -> float:
    """Return the elapsed seconds for the longest currently-running subagent."""
    if db_path is None or aiosqlite is None:
        return 0.0
    p = Path(db_path)
    if not p.exists():
        return 0.0
    try:
        async with aiosqlite.connect(str(p)) as conn:
            cursor = await conn.execute(
                "SELECT started_at FROM subagent_runs "
                "WHERE phase IN ('spawned', 'running')",
            )
            longest = 0.0
            now = datetime.now(timezone.utc)
            async for (started_at,) in cursor:
                if not started_at:
                    continue
                try:
                    start = datetime.fromisoformat(
                        str(started_at).replace("Z", "+00:00"),
                    )
                except Exception:
                    continue
                seconds = max(0.0, (now - start).total_seconds())
                if seconds > longest:
                    longest = seconds
            await cursor.close()
            return longest
    except Exception:
        return 0.0


async def _count_running(db_path: str | Path | None) -> int:
    if db_path is None or aiosqlite is None:
        return 0
    p = Path(db_path)
    if not p.exists():
        return 0
    try:
        async with aiosqlite.connect(str(p)) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM subagent_runs WHERE phase IN ('spawned', 'running')",
            )
            row = await cursor.fetchone()
            await cursor.close()
            return int(row[0]) if row is not None else 0
    except Exception:
        return 0


def _coerce_ok(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        return bool(int(value))  # type: ignore[arg-type]
    except Exception:
        return None


def _split_usage(usage_json: str | None) -> tuple[int, int]:
    if not usage_json:
        return 0, 0
    try:
        usage = json.loads(usage_json)
    except Exception:
        return 0, 0
    if not isinstance(usage, dict):
        return 0, 0
    return (
        int(usage.get("prompt_tokens", 0) or 0),
        int(usage.get("completion_tokens", 0) or 0),
    )


def _duration_ms(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        return max(0.0, (end - start).total_seconds() * 1000.0)
    except Exception:
        return None


def _iso_24h_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
