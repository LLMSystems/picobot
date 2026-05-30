"""Tests for the metrics aggregators that read existing tables."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("aiosqlite")

from simplified_chatbot.metrics.aggregators.api_stats import summarize_api_stats
from simplified_chatbot.metrics.aggregators.messages import aggregate_messages
from simplified_chatbot.metrics.aggregators.sessions import (
    aggregate_sessions,
    list_active_session_ids,
)
from simplified_chatbot.metrics.aggregators.subagents import (
    aggregate_subagents,
    aggregate_subagents_for_session,
)
from simplified_chatbot.metrics.aggregators.tokens import summarize_chat_usage
from simplified_chatbot.metrics.recorders import ApiStatsRecord, ChatUsageRecord
from simplified_chatbot.runtime.session_store import (
    AioSQLiteSessionStore,
    AioSQLiteSubagentStore,
)


# ---- session aggregator ----------------------------------------------------


def test_aggregate_sessions_counts_total_and_recent(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSessionStore(db_path)

    async def setup() -> None:
        await store.create_session("active-1")
        await store.create_session("active-2")
        # Touch updated_at via save_history (which sets updated_at to now).
        await store.save_history(
            "active-1", [{"role": "user", "content": "hi"}],
        )

    asyncio.run(setup())
    stats = asyncio.run(aggregate_sessions(db_path))
    assert stats.total_sessions == 2
    assert stats.new_24h == 2  # both created within the last 24h
    assert stats.active_24h >= 1


def test_aggregate_sessions_handles_missing_db(tmp_path):
    stats = asyncio.run(aggregate_sessions(tmp_path / "missing.db"))
    assert stats.total_sessions == 0
    assert stats.active_24h == 0


def test_list_active_session_ids_returns_recent_first(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSessionStore(db_path)

    async def setup() -> None:
        await store.create_session("old")
        await store.create_session("new")
        await store.save_history("new", [{"role": "user", "content": "ping"}])

    asyncio.run(setup())
    ids = asyncio.run(list_active_session_ids(db_path))
    assert "new" in ids
    assert ids.index("new") == 0


# ---- message aggregator ----------------------------------------------------


def test_aggregate_messages_counts_iterations_and_tools(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSessionStore(db_path)
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "tc-1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                },
                {
                    "id": "tc-2",
                    "type": "function",
                    "function": {"name": "exec", "arguments": "{}"},
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "tc-1",
            "name": "read_file",
            "content": "hello",  # not a JSON dict → counts as success
        },
        {
            "role": "tool",
            "tool_call_id": "tc-2",
            "name": "exec",
            "content": json.dumps({"ok": False, "stderr": "boom"}),
        },
        {"role": "assistant", "content": "done"},
    ]

    async def setup() -> None:
        await store.save_history("s1", history)

    asyncio.run(setup())
    agg = asyncio.run(aggregate_messages(db_path))
    assert agg.assistant_turns == 2
    assert agg.tool_calls_total == 2
    assert agg.tool_success_total == 1
    assert agg.tool_failure_total == 1
    assert pytest.approx(agg.tool_success_rate) == 0.5
    assert agg.tools_by_name["read_file"].success == 1
    assert agg.tools_by_name["exec"].failure == 1


def test_aggregate_messages_session_filter(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSessionStore(db_path)
    history_a = [
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": "y"},
    ]
    history_b = [{"role": "user", "content": "z"}]

    async def setup() -> None:
        await store.save_history("a", history_a)
        await store.save_history("b", history_b)

    asyncio.run(setup())
    agg_a = asyncio.run(aggregate_messages(db_path, session_id="a"))
    agg_b = asyncio.run(aggregate_messages(db_path, session_id="b"))
    assert agg_a.assistant_turns == 1
    assert agg_b.assistant_turns == 0


# ---- subagent aggregator ---------------------------------------------------


def test_aggregate_subagents_summarises_runs(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSubagentStore(db_path)
    now = datetime.now(timezone.utc)

    async def setup() -> None:
        await store.upsert_run(
            {
                "task_id": "t1",
                "parent_session_id": "s1",
                "label": "alpha",
                "task": "do stuff",
                "workspace": None,
                "phase": "done",
                "started_at": (now - timedelta(seconds=3)).isoformat(),
                "finished_at": now.isoformat(),
                "stop_reason": "stop",
                "ok": True,
                "error": None,
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                "tool_events": [],
                "final_content": "ok",
                "model": "gpt-x",
            },
        )
        await store.upsert_run(
            {
                "task_id": "t2",
                "parent_session_id": "s1",
                "label": "beta",
                "task": "fail",
                "workspace": None,
                "phase": "failed",
                "started_at": (now - timedelta(seconds=1)).isoformat(),
                "finished_at": now.isoformat(),
                "stop_reason": "error",
                "ok": False,
                "error": "nope",
                "usage": {"prompt_tokens": 5, "completion_tokens": 0},
                "tool_events": [],
                "final_content": None,
                "model": "gpt-x",
            },
        )
        await store.upsert_run(
            {
                "task_id": "t3",
                "parent_session_id": "s1",
                "label": "live",
                "task": "ongoing",
                "workspace": None,
                "phase": "running",
                "started_at": now.isoformat(),
                "finished_at": None,
                "stop_reason": None,
                "ok": None,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": None,
                "model": "gpt-x",
            },
        )

    asyncio.run(setup())
    stats = asyncio.run(aggregate_subagents(db_path))
    assert stats.runs_24h == 3
    assert stats.running_now == 1
    assert pytest.approx(stats.success_rate_24h) == 0.5
    assert stats.tokens_in_24h == 105
    assert stats.tokens_out_24h == 50

    per_session = asyncio.run(aggregate_subagents_for_session(db_path, "s1"))
    assert per_session.runs_total == 3
    assert per_session.success_total == 1
    assert per_session.failure_total == 1
    assert per_session.tokens_by_model["gpt-x"]["tokens_in"] == 105


# ---- api stats summary -----------------------------------------------------


def test_summarize_api_stats_groups_by_endpoint():
    records = [
        ApiStatsRecord(ts=0.0, endpoint="/chat", status_code=200, duration_ms=10),
        ApiStatsRecord(ts=0.0, endpoint="/chat", status_code=500, duration_ms=20),
        ApiStatsRecord(ts=0.0, endpoint="/sessions", status_code=404, duration_ms=5),
        ApiStatsRecord(ts=0.0, endpoint="/chat", status_code=200, duration_ms=30),
    ]
    summary = summarize_api_stats(records, records)
    assert pytest.approx(summary.qps_1m) == 4 / 60
    assert pytest.approx(summary.error_4xx_rate_1h) == 0.25
    assert pytest.approx(summary.error_5xx_rate_1h) == 0.25
    by_endpoint = {e.endpoint: e for e in summary.top_endpoints_1h}
    assert by_endpoint["/chat"].count == 3
    assert by_endpoint["/chat"].error_5xx == 1
    assert by_endpoint["/sessions"].error_4xx == 1


# ---- token usage summary ---------------------------------------------------


def test_summarize_chat_usage_aggregates_by_model():
    from time import monotonic

    now = monotonic()
    records = [
        ChatUsageRecord(
            ts=now,
            session_id="a",
            model="gpt-x",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
        ChatUsageRecord(
            ts=now,
            session_id="a",
            model="gpt-x",
            prompt_tokens=20,
            completion_tokens=10,
            total_tokens=30,
        ),
        ChatUsageRecord(
            ts=now,
            session_id="b",
            model="gpt-y",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
    ]
    summary = summarize_chat_usage(records)
    assert summary.tokens_in_24h == 31
    assert summary.tokens_out_24h == 16
    by_model = {entry.model: entry for entry in summary.by_model_24h}
    assert by_model["gpt-x"].tokens_in == 30
    assert by_model["gpt-y"].tokens_in == 1
