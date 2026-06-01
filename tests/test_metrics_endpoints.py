"""End-to-end tests for the /metrics endpoints via FastAPI TestClient."""

from __future__ import annotations

import asyncio
import sqlite3
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient

from simplified_chatbot.agent.types import Message
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app


class _DummyResult:
    def __init__(self, content: str, messages: list[Message]) -> None:
        self.content = content
        self.messages = messages
        self.model = "dummy-model"
        self.provider = "dummy"
        self.usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        self.tools_used = []
        self.stop_reason = "stop"


class _DummyChatbot:
    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event=None,
    ) -> _DummyResult:
        history = history or []
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"echo:{message}"},
        ]
        return _DummyResult(content=f"echo:{message}", messages=messages)

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ) -> _DummyResult:
        if on_delta is not None:
            on_delta("echo:")
            on_delta(message)
        return await self.run_async(message, history=history, on_event=on_event)

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() not used in tests")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() not used in tests")


class _MetricsEventChatbot:
    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event=None,
    ) -> _DummyResult:
        history = history or []
        if on_event is not None:
            on_event(
                "llm_call_finished",
                {
                    "model": "gpt-4.1-mini",
                    "latency_ms": 9000,
                    "ttft_ms": None,
                    "success": True,
                    "error_type": None,
                    "purpose": "memory_compaction",
                },
            )
            on_event(
                "llm_call_finished",
                {
                    "model": "gpt-4.1-mini",
                    "latency_ms": 1200,
                    "ttft_ms": 600,
                    "success": True,
                    "error_type": None,
                },
            )
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"echo:{message}"},
        ]
        return _DummyResult(content=f"echo:{message}", messages=messages)

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ) -> _DummyResult:
        if on_delta is not None:
            on_delta("echo:")
            on_delta(message)
        return await self.run_async(message, history=history, on_event=on_event)

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() not used in tests")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() not used in tests")


def _make_app(tmp_path) -> TestClient:
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    app = create_app(runtime=runtime)
    return TestClient(app)


def test_metrics_current_returns_well_formed_snapshot(tmp_path):
    client = _make_app(tmp_path)
    resp = client.get("/metrics/current")
    assert resp.status_code == 200
    body = resp.json()

    assert set(body.keys()) >= {"ts", "system", "agent", "subagents", "api", "usage"}
    assert "cpu_percent" in body["system"]
    assert "active_sse_connections" in body["system"]
    assert "sessions_total" in body["agent"]
    assert "runs_24h" in body["subagents"]
    assert {"qps_1m", "latency_p50_ms", "error_4xx_rate_1h", "error_5xx_rate_1h"}.issubset(
        body["api"].keys(),
    )
    assert "by_model_24h" in body["usage"]


def test_chat_call_pushes_usage_into_metrics(tmp_path):
    client = _make_app(tmp_path)
    chat_resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
    )
    assert chat_resp.status_code == 200

    metrics = client.get("/metrics/current").json()
    by_model = {entry["model"]: entry for entry in metrics["usage"]["by_model_24h"]}
    assert "dummy-model" in by_model
    assert by_model["dummy-model"]["tokens_in"] == 10
    assert by_model["dummy-model"]["tokens_out"] == 20


def test_memory_compaction_llm_events_are_excluded_from_metrics(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MetricsEventChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    chat_resp = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hi"},
    )
    assert chat_resp.status_code == 200

    conn = sqlite3.connect(str(tmp_path / "sessions.db"))
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(latency_ms), MAX(latency_ms) FROM llm_call_events",
        ).fetchone()
    finally:
        conn.close()

    assert row == (1, 1200, 1200)


def test_metrics_session_returns_per_session_detail(tmp_path):
    client = _make_app(tmp_path)
    client.post("/chat", json={"session_id": "s1", "message": "hi"})

    resp = client.get("/metrics/sessions/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"
    assert body["message_count"] >= 2  # user + assistant
    assert body["iterations_total"] >= 1
    assert body["chat_tokens_in"] == 10
    assert body["chat_tokens_out"] == 20


def test_metrics_session_404_for_missing_session(tmp_path):
    client = _make_app(tmp_path)
    resp = client.get("/metrics/sessions/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_api_stats_middleware_excludes_metrics_paths(tmp_path):
    client = _make_app(tmp_path)
    # Generate some traffic on the metrics endpoint itself.
    for _ in range(3):
        client.get("/metrics/current")
    # And on a real (non-metrics) endpoint.
    client.get("/health")

    snap = client.get("/metrics/current").json()
    endpoints = {e["endpoint"] for e in snap["api"]["top_endpoints_1h"]}
    # The middleware should not register any /metrics traffic.
    assert not any(ep.startswith("/metrics") for ep in endpoints)
    assert "/health" in endpoints


def test_api_stats_tracks_4xx_separately(tmp_path):
    client = _make_app(tmp_path)
    # Trigger a 404 on a session-detail endpoint to populate 4xx.
    client.get("/sessions/does-not-exist/messages")

    snap = client.get("/metrics/current").json()
    assert snap["api"]["error_4xx_rate_1h"] > 0.0
    assert snap["api"]["error_5xx_rate_1h"] == 0.0
