"""Unit tests for SnapshotStore CRUD and bucket queries."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("aiosqlite")

from simplified_chatbot.metrics.snapshot_store import SnapshotRow, SnapshotStore


def _row(ts: str, metric: str, value: float, **kwargs) -> SnapshotRow:
    return SnapshotRow(
        ts=ts,
        category=kwargs.get("category", "system"),
        metric=metric,
        dim_key=kwargs.get("dim_key"),
        dim_value=kwargs.get("dim_value"),
        value_num=value,
    )


def test_snapshot_store_inserts_and_counts(tmp_path):
    store = SnapshotStore(tmp_path / "metrics.db")

    async def run() -> int:
        now = datetime.now(timezone.utc).isoformat()
        await store.insert_rows([
            _row(now, "cpu_percent", 10.0),
            _row(now, "rss_bytes", 1024.0),
        ])
        return await store.row_count()

    assert asyncio.run(run()) == 2


def test_snapshot_store_buckets_average_per_window(tmp_path):
    store = SnapshotStore(tmp_path / "metrics.db")
    base = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)

    async def setup() -> None:
        rows = []
        for offset, value in [(0, 10.0), (30, 20.0), (60, 100.0), (90, 200.0)]:
            ts = (base + timedelta(seconds=offset)).isoformat()
            rows.append(_row(ts, "cpu_percent", value))
        await store.insert_rows(rows)

    asyncio.run(setup())
    grouped = asyncio.run(
        store.fetch_history(
            metric="cpu_percent",
            since_iso=(base - timedelta(minutes=1)).isoformat(),
            bucket_seconds=60,
        ),
    )
    assert len(grouped) == 1
    _key, points = grouped[0]
    values = [p.value for p in points]
    # 0s+30s bucket averages to 15; 60s+90s averages to 150.
    assert values == [15.0, 150.0]


def test_snapshot_store_groups_by_dim_value(tmp_path):
    store = SnapshotStore(tmp_path / "metrics.db")
    ts = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc).isoformat()

    async def setup() -> None:
        await store.insert_rows([
            _row(ts, "tokens_in_24h", 100.0, category="usage", dim_key="model", dim_value="m1"),
            _row(ts, "tokens_in_24h", 50.0, category="usage", dim_key="model", dim_value="m2"),
        ])

    asyncio.run(setup())
    grouped = asyncio.run(
        store.fetch_history(
            metric="tokens_in_24h",
            since_iso=(datetime(2026, 5, 30, 11, 59, 0, tzinfo=timezone.utc)).isoformat(),
            bucket_seconds=300,
        ),
    )
    by_model = {k.dim_value: pts[0].value for k, pts in grouped}
    assert by_model == {"m1": 100.0, "m2": 50.0}


def test_snapshot_store_prune_removes_old(tmp_path):
    store = SnapshotStore(tmp_path / "metrics.db")
    now = datetime.now(timezone.utc)
    fresh_ts = now.isoformat()
    stale_ts = (now - timedelta(days=10)).isoformat()

    async def run() -> tuple[int, int]:
        await store.insert_rows([
            _row(fresh_ts, "cpu_percent", 5.0),
            _row(stale_ts, "cpu_percent", 99.0),
        ])
        deleted = await store.prune_older_than(retention_days=7)
        return deleted, await store.row_count()

    deleted, remaining = asyncio.run(run())
    assert deleted == 1
    assert remaining == 1
