"""Tests for the shared SQLite open helper.

The big claim we're verifying:

- `open_async` enables WAL on the DB file (persistent), and
- sets the per-connection knobs (synchronous=NORMAL, big cache, mem temp,
  5 s busy_timeout) every time a connection is opened.

If any of these regress, every store across the app picks up the wrong
defaults — so the helper-level assertions stand in for blanket coverage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simplified_chatbot.runtime.sqlite_pragmas import (
    _PRAGMAS,
    apply_pragmas_sync,
    open_async,
)


@pytest.mark.asyncio
async def test_open_async_enables_wal(tmp_path: Path) -> None:
    db = tmp_path / "wal.db"
    async with open_async(db) as conn:
        # journal_mode is persistent at the file level — it stays even on
        # subsequent fresh connections.
        cur = await conn.execute("PRAGMA journal_mode")
        row = await cur.fetchone()
        await cur.close()
        assert row is not None
        assert str(row[0]).lower() == "wal"

    # New connection via raw sqlite3 should also report WAL since journal_mode
    # is persistent at the DB-file level.
    raw = sqlite3.connect(str(db))
    try:
        mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        raw.close()


@pytest.mark.asyncio
async def test_open_async_sets_per_connection_pragmas(tmp_path: Path) -> None:
    db = tmp_path / "pragmas.db"
    async with open_async(db) as conn:
        sync = await (await conn.execute("PRAGMA synchronous")).fetchone()
        cache = await (await conn.execute("PRAGMA cache_size")).fetchone()
        temp = await (await conn.execute("PRAGMA temp_store")).fetchone()
        busy = await (await conn.execute("PRAGMA busy_timeout")).fetchone()
    # synchronous: 1 == NORMAL
    assert int(sync[0]) == 1
    # cache_size: negative means KiB; -32000 = 32 MiB
    assert int(cache[0]) == -32000
    # temp_store: 2 == MEMORY
    assert int(temp[0]) == 2
    # busy_timeout: 5000 ms
    assert int(busy[0]) == 5000


@pytest.mark.asyncio
async def test_open_async_pragmas_list_matches_assertions(tmp_path: Path) -> None:
    # Guard against silent drift: if someone reorders / adds a pragma,
    # they must update the helper docstring AND this test together.
    assert _PRAGMAS == (
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
        "PRAGMA cache_size=-32000",
        "PRAGMA temp_store=MEMORY",
        "PRAGMA busy_timeout=5000",
    )


def test_apply_pragmas_sync(tmp_path: Path) -> None:
    db = tmp_path / "sync.db"
    conn = sqlite3.connect(str(db))
    try:
        apply_pragmas_sync(conn)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        assert int(sync) == 1
    finally:
        conn.close()


def test_apply_pragmas_sync_swallows_errors() -> None:
    # The helper must never raise — a closed connection should just be a no-op
    # rather than crash callers in the hot path.
    conn = sqlite3.connect(":memory:")
    conn.close()
    # Should not raise even though the connection is dead.
    apply_pragmas_sync(conn)
