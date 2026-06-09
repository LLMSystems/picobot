"""Integration tests for snapshot writer + snapshot task + history endpoint."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from conftest import register_test_user
from simplified_chatbot.agent.types import Message
from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.metrics.snapshot_store import SnapshotStore
from simplified_chatbot.metrics.snapshot_task import SnapshotTask
from simplified_chatbot.metrics.snapshot_writer import (
    build_global_rows,
    build_session_rows,
)
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app


class _DummyResult:
    def __init__(self, content: str, messages: list[Message]) -> None:
        self.content = content
        self.messages = messages
        self.model = "gpt-x"
        self.provider = "p"
        self.usage = {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}
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
        return _DummyResult(content=f"echo:{message}", messages=msgs)

    async def run_stream_async(self, *a, **k):
        return await self.run_async(*a, **k)

    def run(self, *a, **k):
        raise AssertionError("sync not used")

    def run_stream(self, *a, **k):
        raise AssertionError("sync not used")


# ---- writer ----------------------------------------------------------------


def test_build_global_rows_covers_all_categories():
    snapshot = {
        "system": {
            "cpu_percent": 12.0,
            "rss_bytes": 1024,
            "threads": 4,
            "db_file_bytes": 4096,
            "workspace_total_bytes": 50_000,
            "workspace_session_count": 3,
            "active_sse_connections": {"chat": 2, "session_events": 1},
        },
        "agent": {
            "sessions_total": 5,
            "sessions_active_24h": 3,
            "sessions_new_24h": 1,
            "message_count_total": 42,
            "iterations_total": 12,
            "tool_calls_total": 8,
            "tool_success_rate": 0.875,
        },
        "subagents": {
            "runs_24h": 2,
            "success_rate_24h": 1.0,
            "duration_p50_ms": 100.0,
            "duration_p95_ms": 200.0,
            "running_now": 0,
            "tokens_in_24h": 10,
            "tokens_out_24h": 5,
        },
        "api": {
            "qps_1m": 0.5,
            "latency_p50_ms": 20.0,
            "latency_p95_ms": 80.0,
            "error_4xx_rate_1h": 0.0,
            "error_5xx_rate_1h": 0.0,
            "top_endpoints_1h": [
                {
                    "endpoint": "/chat",
                    "count": 3,
                    "latency_p50_ms": 30.0,
                    "latency_p95_ms": 60.0,
                    "error_4xx": 0,
                    "error_5xx": 0,
                },
            ],
        },
        "usage": {
            "tokens_in_24h": 100,
            "tokens_out_24h": 50,
            "by_model_24h": [
                {"model": "gpt-x", "tokens_in": 70, "tokens_out": 30},
            ],
        },
    }
    rows = build_global_rows(ts="2026-05-30T12:00:00Z", snapshot=snapshot)
    metrics_by_cat = {(r.category, r.metric, r.dim_value) for r in rows}

    assert ("system", "cpu_percent", None) in metrics_by_cat
    assert ("system", "active_sse_connections", "chat") in metrics_by_cat
    assert ("agent", "tool_success_rate", None) in metrics_by_cat
    assert ("subagents", "running_now", None) in metrics_by_cat
    assert ("api", "qps_1m", None) in metrics_by_cat
    assert ("api", "endpoint_count", "/chat") in metrics_by_cat
    assert ("usage", "tokens_in_24h", "gpt-x") in metrics_by_cat


def test_build_session_rows_writes_per_session_dim():
    session_snapshot = {
        "message_count": 10,
        "iterations_total": 4,
        "tool_calls_total": 6,
        "chat_tokens_in": 100,
        "chat_tokens_out": 50,
        "subagent_runs": 1,
        "subagent_tokens_in": 5,
        "subagent_tokens_out": 2,
    }
    rows = build_session_rows(
        ts="2026-05-30T12:00:00Z",
        session_id="abc",
        session_snapshot=session_snapshot,
    )
    metrics = {r.metric: r for r in rows}
    assert "message_count" in metrics
    assert metrics["message_count"].dim_key == "session_id"
    assert metrics["message_count"].dim_value == "abc"
    assert metrics["chat_tokens_in"].value_num == 100.0


# ---- snapshot task ---------------------------------------------------------


def test_snapshot_task_tick_writes_rows(tmp_path):
    db_path = tmp_path / "sessions.db"
    store = AioSQLiteSessionStore(db_path)
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    snapshot_store = SnapshotStore(tmp_path / "metrics.db")
    service = MetricsService(
        db_path=db_path,
        workspace_root_dir=None,
        snapshot_store=snapshot_store,
    )

    async def go() -> int:
        # Seed one session so per-session writes happen too.
        await store.create_session("s1")
        await store.save_history(
            "s1",
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        )
        task = SnapshotTask(
            service=service,
            store=snapshot_store,
            db_path=str(db_path),
            interval_seconds=60,
            retention_days=7,
        )
        await task.tick_once()
        return await snapshot_store.row_count()

    assert asyncio.run(go()) > 0


# ---- endpoint --------------------------------------------------------------


def test_history_endpoint_returns_buckets(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)  # /metrics is admin-only; "tester" is admin in tests

    # Force one snapshot to land in the table.
    task = app.state.snapshot_task
    asyncio.run(task.tick_once())

    resp = client.get(
        "/metrics/history",
        params={"range": "1h", "series": "cpu_percent,tokens_in_24h"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "1h"
    assert body["bucket"] == "1m"
    assert isinstance(body["series"], list)
    metrics_returned = {s["metric"] for s in body["series"]}
    # cpu_percent should appear; tokens_in_24h may have per-model breakdowns.
    assert "cpu_percent" in metrics_returned


def test_history_endpoint_rejects_bad_range(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)  # /metrics is admin-only; "tester" is admin in tests

    resp = client.get(
        "/metrics/history",
        params={"range": "999h", "series": "cpu_percent"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "METRICS_RANGE_INVALID"


def test_history_endpoint_requires_series(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)  # /metrics is admin-only; "tester" is admin in tests

    resp = client.get("/metrics/history", params={"range": "1h"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "METRICS_SERIES_REQUIRED"


# ---- live stream -----------------------------------------------------------


def test_stream_metrics_snapshots_yields_one_frame_per_tick(tmp_path):
    """Drive the SSE generator directly without going through the HTTP layer.

    httpx.ASGITransport buffers the entire response, so an infinite SSE stream
    deadlocks against it. Testing the generator function directly side-steps
    that limitation entirely.
    """
    from simplified_chatbot.metrics.service import MetricsService
    from simplified_chatbot.server.endpoints_metrics import stream_metrics_snapshots

    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)  # ensures schema is set up
    svc = MetricsService(
        db_path=tmp_path / "sessions.db",
        workspace_root_dir=None,
    )

    async def is_disconnected() -> bool:
        return False

    async def go() -> list[bytes]:
        frames: list[bytes] = []
        agen = stream_metrics_snapshots(svc, is_disconnected, tick_seconds=0.01)
        try:
            frames.append(await agen.__anext__())
            frames.append(await agen.__anext__())
        finally:
            await agen.aclose()
        return frames

    frames = asyncio.run(go())
    assert len(frames) == 2
    for frame in frames:
        text = frame.decode("utf-8")
        assert "event: metrics_snapshot" in text
        assert '"system":' in text
        assert '"usage":' in text


def test_stream_metrics_snapshots_exits_on_disconnect(tmp_path):
    """When `is_disconnected()` flips to True the generator must stop cleanly."""
    from simplified_chatbot.metrics.service import MetricsService
    from simplified_chatbot.server.endpoints_metrics import stream_metrics_snapshots

    svc = MetricsService(db_path=tmp_path / "sessions.db", workspace_root_dir=None)

    state = {"disconnected": False}

    async def is_disconnected() -> bool:
        return state["disconnected"]

    async def go() -> int:
        agen = stream_metrics_snapshots(svc, is_disconnected, tick_seconds=0.01)
        count = 0
        # Consume one frame, then trip the disconnect flag and confirm
        # the generator stops on the next iteration.
        async for _ in agen:
            count += 1
            state["disconnected"] = True
            if count >= 5:
                break
        return count

    count = asyncio.run(go())
    # Should stop after the first frame's tick observes the disconnect flag.
    assert count == 1
