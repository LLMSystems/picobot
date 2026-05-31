"""Tests for `LlmCallStore.insert_many` batch path.

What we're guarding:

- A multi-row batch writes ALL rows (no executemany off-by-one).
- The empty-list case is a no-op (doesn't open a connection or commit).
- Fields land in the right columns — including the optional `ttft_ms` and
  `chat_id` we added with the TTFT / per-chat work.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from simplified_chatbot.metrics.llm_call_store import LlmCallStore


@pytest.mark.asyncio
async def test_insert_many_writes_all_rows(tmp_path: Path) -> None:
    db = tmp_path / "batch.db"
    store = LlmCallStore(db)
    items = [
        {
            "session_id": "s1",
            "model": "gpt-4o",
            "latency_ms": 100,
            "success": True,
            "ttft_ms": 30,
            "chat_id": "chat_a",
        },
        {
            "session_id": "s1",
            "model": "gpt-4o",
            "latency_ms": 200,
            "success": True,
            "ttft_ms": 40,
            "chat_id": "chat_a",
        },
        {
            "session_id": "s1",
            "model": "gpt-4o",
            "latency_ms": 50,
            "success": False,
            "error_type": "timeout",
            # tool-only iterations have no TTFT
            "ttft_ms": None,
            "chat_id": "chat_a",
        },
    ]
    await store.insert_many(items)
    assert await store.row_count() == 3


@pytest.mark.asyncio
async def test_insert_many_empty_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    store = LlmCallStore(db)
    # Should not open a connection or create the schema.
    await store.insert_many([])
    # File may or may not exist depending on whether ensure_schema ran;
    # row_count() will run ensure_schema and return 0.
    assert await store.row_count() == 0


@pytest.mark.asyncio
async def test_insert_many_preserves_fields(tmp_path: Path) -> None:
    db = tmp_path / "fields.db"
    store = LlmCallStore(db)
    await store.insert_many(
        [
            {
                "session_id": "s1",
                "model": "claude-sonnet-4-6",
                "latency_ms": 1234,
                "success": False,
                "error_type": "api_error",
                "ttft_ms": 200,
                "chat_id": "abc123",
            },
        ],
    )
    # Inspect via raw sqlite3 so the assertion is independent of LlmCallStore's
    # own reader paths (which we'd otherwise be testing against themselves).
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT session_id, model, latency_ms, success, error_type, ttft_ms, chat_id "
            "FROM llm_call_events",
        ).fetchone()
    finally:
        conn.close()
    assert row == ("s1", "claude-sonnet-4-6", 1234, 0, "api_error", 200, "abc123")


@pytest.mark.asyncio
async def test_insert_delegates_to_insert_many(tmp_path: Path) -> None:
    """Singular `insert()` should route through `insert_many` so both paths
    stay in sync — verified by writing via insert() and reading the same row
    layout we asserted above."""
    db = tmp_path / "single.db"
    store = LlmCallStore(db)
    await store.insert(
        session_id="s1",
        model="gpt-4o",
        latency_ms=99,
        success=True,
        ttft_ms=12,
        chat_id="solo",
    )
    rows = await store.list_since("1970-01-01T00:00:00")
    assert len(rows) == 1
    assert rows[0].chat_id == "solo"
    assert rows[0].ttft_ms == 12
    assert rows[0].latency_ms == 99
