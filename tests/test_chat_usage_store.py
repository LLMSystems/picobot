"""Tests for the chat_usage_events store + end-to-end persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from simplified_chatbot.agent.types import Message
from simplified_chatbot.metrics.chat_usage_store import ChatUsageStore
from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app


class _DummyResult:
    def __init__(self, content, messages, *, model="gpt-x"):
        self.content = content
        self.messages = messages
        self.model = model
        self.provider = "dummy"
        self.usage = {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12}
        self.tools_used = []
        self.stop_reason = "stop"


class _DummyChatbot:
    async def run_async(self, message, history=None, *, on_event=None):
        history = history or []
        msgs = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"echo:{message}"},
        ]
        return _DummyResult(f"echo:{message}", msgs)

    async def run_stream_async(self, *a, **k):
        return await self.run_async(*a, **k)

    def run(self, *a, **k):
        raise AssertionError("sync not used")

    def run_stream(self, *a, **k):
        raise AssertionError("sync not used")


# ---- store CRUD ------------------------------------------------------------


def test_store_insert_and_aggregate(tmp_path):
    store = ChatUsageStore(tmp_path / "metrics.db")

    async def go() -> tuple[int, int, list]:
        for i in range(3):
            await store.insert(
                session_id="s1" if i < 2 else "s2",
                model="gpt-x",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        agg = await store.aggregate_since(since)
        return agg.tokens_in, agg.tokens_out, agg.by_model

    tokens_in, tokens_out, by_model = asyncio.run(go())
    assert tokens_in == 30  # 3 × 10
    assert tokens_out == 15  # 3 × 5
    assert len(by_model) == 1
    assert by_model[0].model == "gpt-x"


def test_store_aggregate_filters_by_session(tmp_path):
    store = ChatUsageStore(tmp_path / "metrics.db")

    async def go() -> tuple[int, int]:
        await store.insert(
            session_id="alpha",
            model="gpt-x",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        await store.insert(
            session_id="beta",
            model="gpt-y",
            prompt_tokens=999,
            completion_tokens=999,
            total_tokens=1998,
        )
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        agg = await store.aggregate_since(since, session_id="alpha")
        return agg.tokens_in, agg.tokens_out

    assert asyncio.run(go()) == (100, 50)


def test_store_prune_drops_old_rows(tmp_path):
    store = ChatUsageStore(tmp_path / "metrics.db")

    async def go() -> tuple[int, int]:
        # 10 days ago — should be pruned.
        await store.insert(
            session_id="s",
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            ts=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        )
        # Today — kept.
        await store.insert(
            session_id="s",
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )
        deleted = await store.prune_older_than(retention_days=7)
        remaining = await store.row_count()
        return deleted, remaining

    deleted, remaining = asyncio.run(go())
    assert deleted == 1
    assert remaining == 1


# ---- MetricsService DB-backed aggregation ---------------------------------


def test_service_uses_store_when_provided(tmp_path):
    db_path = tmp_path / "sessions.db"
    # Touch a session store first so message-aggregator queries don't 404.
    AioSQLiteSessionStore(db_path)
    store = ChatUsageStore(db_path)
    svc = MetricsService(
        db_path=db_path,
        workspace_root_dir=None,
        chat_usage_store=store,
    )

    async def go() -> tuple[int, int]:
        # Pre-populate the store as if a previous process had written usage.
        await store.insert(
            session_id="prior",
            model="gpt-old",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
        )
        # Ensure session_messages table exists (aggregator joins it).
        sess_store = AioSQLiteSessionStore(db_path)
        await sess_store.create_session("dummy")
        snap = await svc.build_current_snapshot()
        return snap["usage"]["tokens_in_24h"], snap["usage"]["tokens_out_24h"]

    tokens_in, tokens_out = asyncio.run(go())
    assert tokens_in == 200
    assert tokens_out == 100


def test_service_falls_back_to_ring_without_store():
    svc = MetricsService(
        db_path=None,
        workspace_root_dir=None,
        chat_usage_store=None,
    )
    svc.chat_usage.record(
        session_id="s",
        model="m",
        usage={"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10},
    )

    async def go() -> tuple[int, int]:
        snap = await svc.build_current_snapshot()
        return snap["usage"]["tokens_in_24h"], snap["usage"]["tokens_out_24h"]

    tokens_in, tokens_out = asyncio.run(go())
    assert tokens_in == 9
    assert tokens_out == 1


# ---- end-to-end: persistence across "restart" -----------------------------


def test_chat_usage_survives_restart(tmp_path):
    """First process writes usage; second process (fresh app) reads it back."""
    db_path = tmp_path / "sessions.db"

    # ---- "process 1" ----
    store_a = AioSQLiteSessionStore(db_path)
    runtime_a = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store_a)
    client_a = TestClient(create_app(runtime=runtime_a))
    client_a.post("/chat", json={"session_id": "abc", "message": "hi"})
    client_a.post("/chat", json={"session_id": "abc", "message": "again"})
    snap_a = client_a.get("/metrics/current").json()
    assert snap_a["usage"]["tokens_in_24h"] == 10  # 2 × 5

    # ---- "process 2" (fresh runtime + app on same db) ----
    store_b = AioSQLiteSessionStore(db_path)
    runtime_b = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store_b)
    client_b = TestClient(create_app(runtime=runtime_b))
    snap_b = client_b.get("/metrics/current").json()
    # Without persistence this would be 0 (in-memory ring is fresh).
    assert snap_b["usage"]["tokens_in_24h"] == 10
    assert snap_b["usage"]["tokens_out_24h"] == 14  # 2 × 7

    # Per-session drill-down also sees it.
    sess = client_b.get("/metrics/sessions/abc").json()
    assert sess["chat_tokens_in"] == 10
    assert sess["chat_tokens_out"] == 14
