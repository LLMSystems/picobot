"""AioSQLite-backed storage for the metrics_snapshots table.

Long-format design: every metric sample is one row tagged with a (category,
metric, dim_key, dim_value) tuple. New metrics never require an ALTER TABLE.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SnapshotRow:
    ts: str
    category: str
    metric: str
    dim_key: str | None = None
    dim_value: str | None = None
    value_num: float | None = None
    value_text: str | None = None


@dataclass(frozen=True)
class TimeseriesPoint:
    ts: str
    value: float | None


@dataclass(frozen=True)
class TimeseriesKey:
    category: str
    metric: str
    dim_key: str | None
    dim_value: str | None


_AGGREGATIONS = {"avg", "sum", "min", "max", "last"}
_DEFAULT_AGG = "avg"


class SnapshotStore:
    """Persist and query snapshot rows. Safe to share across the FastAPI app."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "SnapshotStore requires 'aiosqlite'. Install with: pip install aiosqlite",
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
                    CREATE TABLE IF NOT EXISTS metrics_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ts TEXT NOT NULL,
                        category TEXT NOT NULL,
                        metric TEXT NOT NULL,
                        dim_key TEXT,
                        dim_value TEXT,
                        value_num REAL,
                        value_text TEXT
                    )
                    """,
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_metrics_ts "
                    "ON metrics_snapshots(ts)",
                )
                await conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_metrics_cat_metric_ts "
                    "ON metrics_snapshots(category, metric, ts)",
                )
                await conn.commit()
            self._initialized = True

    async def insert_rows(self, rows: Sequence[SnapshotRow]) -> None:
        if not rows:
            return
        await self.ensure_schema()
        payload = [
            (
                r.ts,
                r.category,
                r.metric,
                r.dim_key,
                r.dim_value,
                r.value_num,
                r.value_text,
            )
            for r in rows
        ]
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.executemany(
                """
                INSERT INTO metrics_snapshots
                    (ts, category, metric, dim_key, dim_value, value_num, value_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            await conn.commit()

    async def prune_older_than(self, *, retention_days: int) -> int:
        await self.ensure_schema()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                "DELETE FROM metrics_snapshots WHERE ts < ?",
                (cutoff,),
            )
            await conn.commit()
            return cursor.rowcount or 0

    async def fetch_history(
        self,
        *,
        metric: str,
        since_iso: str,
        bucket_seconds: int,
        dim_key: str | None = None,
        dim_value: str | None = None,
        aggregation: str = _DEFAULT_AGG,
    ) -> list[tuple[TimeseriesKey, list[TimeseriesPoint]]]:
        """Return one timeseries per matched (dim_key, dim_value) combination.

        When `dim_value` is supplied we filter to that exact series; otherwise
        we group by every distinct (dim_key, dim_value) seen — useful for
        per-model or per-endpoint breakdowns.
        """
        await self.ensure_schema()
        agg = aggregation.lower()
        if agg not in _AGGREGATIONS:
            agg = _DEFAULT_AGG
        bucket_seconds = max(1, int(bucket_seconds))

        if agg == "last":
            # Per bucket, take the latest sample by ts.
            sql = """
                WITH ranked AS (
                    SELECT
                        category,
                        dim_key,
                        dim_value,
                        ts,
                        value_num,
                        (CAST(strftime('%s', ts) AS INTEGER) / ?) * ? AS bucket_epoch,
                        ROW_NUMBER() OVER (
                            PARTITION BY category, dim_key, dim_value,
                                (CAST(strftime('%s', ts) AS INTEGER) / ?) * ?
                            ORDER BY ts DESC
                        ) AS rn
                    FROM metrics_snapshots
                    WHERE metric = ? AND ts >= ?
                )
                SELECT category, dim_key, dim_value, bucket_epoch, value_num
                FROM ranked
                WHERE rn = 1
                ORDER BY dim_value, bucket_epoch
            """
            params: tuple[Any, ...] = (
                bucket_seconds, bucket_seconds,
                bucket_seconds, bucket_seconds,
                metric, since_iso,
            )
        else:
            agg_fn = {"avg": "AVG", "sum": "SUM", "min": "MIN", "max": "MAX"}[agg]
            sql = f"""
                SELECT
                    category,
                    dim_key,
                    dim_value,
                    (CAST(strftime('%s', ts) AS INTEGER) / ?) * ? AS bucket_epoch,
                    {agg_fn}(value_num) AS value
                FROM metrics_snapshots
                WHERE metric = ? AND ts >= ?
                {{extra_where}}
                GROUP BY category, dim_key, dim_value, bucket_epoch
                ORDER BY dim_value, bucket_epoch
            """
            extra_where = ""
            params = (bucket_seconds, bucket_seconds, metric, since_iso)
            if dim_key is not None:
                extra_where += " AND dim_key = ?"
                params = (*params, dim_key)
            if dim_value is not None:
                extra_where += " AND dim_value = ?"
                params = (*params, dim_value)
            sql = sql.replace("{extra_where}", extra_where)

        rows: list[tuple[str, str | None, str | None, int, float | None]] = []
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(sql, params)
            async for row in cursor:
                rows.append(tuple(row))  # type: ignore[arg-type]
            await cursor.close()

        grouped: dict[
            TimeseriesKey, list[TimeseriesPoint]
        ] = {}
        for category, dk, dv, bucket_epoch, value in rows:
            key = TimeseriesKey(
                category=category, metric=metric, dim_key=dk, dim_value=dv,
            )
            point = TimeseriesPoint(
                ts=_iso_from_epoch(int(bucket_epoch)),
                value=float(value) if value is not None else None,
            )
            grouped.setdefault(key, []).append(point)
        return list(grouped.items())

    async def row_count(self) -> int:
        await self.ensure_schema()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM metrics_snapshots")
            row = await cursor.fetchone()
            await cursor.close()
            return int(row[0]) if row is not None else 0


def _iso_from_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
