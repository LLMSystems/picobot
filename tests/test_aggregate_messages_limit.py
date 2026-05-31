"""Tests for the row-limit cap on `aggregate_messages`.

The aggregator runs on every snapshot tick (every 10 s) and previously
full-scanned `session_messages`. With the cap, we want to verify two things:

1. The cap *bounds* the rows considered — older rows past the limit are
   ignored (rolling-window semantics).
2. Within the window, tool_call → tool_result pairing still works (we re-sort
   to chronological order inside the SQL subquery).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from simplified_chatbot.metrics.aggregators.messages import aggregate_messages


def _seed_messages(db_path: Path, items: list[dict]) -> None:
    """Insert items as (session_id, position, payload-json) rows."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_messages (
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, position)
            )
            """,
        )
        for i, msg in enumerate(items):
            conn.execute(
                "INSERT INTO session_messages (session_id, position, payload) VALUES (?, ?, ?)",
                (msg.get("session_id", "s1"), i, json.dumps(msg)),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_limit_caps_rows_scanned(tmp_path: Path) -> None:
    """Old rows past the cap shouldn't influence the aggregate counts."""
    db = tmp_path / "cap.db"
    # 50 ancient assistant rows that should be excluded once cap < 50
    seeds = [
        {"role": "assistant", "content": f"old {i}"}
        for i in range(50)
    ]
    # 3 recent rows that SHOULD be in the window: 1 assistant + 1 tool result
    seeds.extend(
        [
            {
                "role": "assistant",
                "content": "calling tool",
                "tool_calls": [
                    {"id": "call_1", "function": {"name": "search"}},
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "search",
                "content": "ok",
            },
        ],
    )
    _seed_messages(db, seeds)

    # Cap at 2 rows → only the last (tool + 1 prior msg) survive. The order
    # we wrote was assistant-with-tool then tool-result, so newest-2 includes
    # both — tool call should pair correctly.
    agg = await aggregate_messages(db, row_limit=2)
    # Only the recent assistant turn was in-window → exactly 1 tool call.
    assert agg.tool_calls_total == 1
    assert agg.tool_success_total == 1
    # message_count counts all rows we saw inside the cap (2 here).
    assert agg.message_count == 2


@pytest.mark.asyncio
async def test_limit_preserves_chronological_pairing(tmp_path: Path) -> None:
    """Inside the window, tool_call → tool_result pairing must still work
    even though we fetched via `ORDER BY rowid DESC LIMIT N`."""
    db = tmp_path / "pair.db"
    # `ok` is parsed from JSON-encoded `content`, not from a top-level field —
    # mirror how tools actually serialize results.
    seeds = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "read"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c1",
            "name": "read",
            "content": json.dumps({"ok": False, "error": "boom"}),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c2", "function": {"name": "read"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c2",
            "name": "read",
            "content": json.dumps({"ok": True}),
        },
    ]
    _seed_messages(db, seeds)

    agg = await aggregate_messages(db, row_limit=10)
    # Two calls of `read`, one success one failure → 50% success rate
    assert agg.tool_calls_total == 2
    entry = agg.tools_by_name["read"]
    assert entry.success == 1
    assert entry.failure == 1


@pytest.mark.asyncio
async def test_session_id_filter_with_limit(tmp_path: Path) -> None:
    """The per-session path also honours the cap."""
    db = tmp_path / "by_session.db"
    seeds = [
        {"session_id": "s1", "role": "user", "content": "hi"},
        {"session_id": "s2", "role": "user", "content": "hi from s2"},
        {"session_id": "s1", "role": "assistant", "content": "hello"},
    ]
    _seed_messages(db, seeds)

    s1_agg = await aggregate_messages(db, session_id="s1", row_limit=100)
    s2_agg = await aggregate_messages(db, session_id="s2", row_limit=100)
    assert s1_agg.message_count == 2
    assert s2_agg.message_count == 1
