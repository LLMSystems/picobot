"""End-to-end tests for the /alerts/* endpoints."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient

from conftest import register_test_user
from simplified_chatbot.agent.types import Message
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app


class _DummyResult:
    def __init__(self, content, messages):
        self.content = content
        self.messages = messages
        self.model = "dummy"
        self.provider = "dummy"
        self.usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
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


def _make_client(tmp_path, alerts_yaml: str | None = None) -> TestClient:
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=store)
    alerts_path = None
    if alerts_yaml is not None:
        p = tmp_path / "alerts.yaml"
        p.write_text(alerts_yaml, encoding="utf-8")
        alerts_path = p
    app = create_app(runtime=runtime, alerts_config_path=alerts_path)
    client = TestClient(app)
    register_test_user(client)  # alerts is admin-only; "tester" is admin in tests
    return client


def test_alerts_active_returns_empty_when_no_rules(tmp_path):
    client = _make_client(tmp_path, alerts_yaml=None)
    resp = client.get("/alerts/active")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "silences": {}}


def test_alerts_rules_lists_configured_rules(tmp_path):
    yaml = """
rules:
  - name: cpu_high
    description: cpu
    severity: warning
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
""".strip()
    client = _make_client(tmp_path, alerts_yaml=yaml)
    body = client.get("/alerts/rules").json()
    assert len(body["rules"]) == 1
    assert body["rules"][0]["name"] == "cpu_high"


def test_alerts_ack_404_for_unknown_event(tmp_path):
    yaml = """
rules:
  - name: cpu_high
    description: cpu
    severity: warning
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
""".strip()
    client = _make_client(tmp_path, alerts_yaml=yaml)
    resp = client.post("/alerts/9999/ack")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ALERT_EVENT_NOT_FOUND"


def test_alerts_silence_and_unsilence(tmp_path):
    yaml = """
rules:
  - name: cpu_high
    description: cpu
    severity: warning
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
""".strip()
    client = _make_client(tmp_path, alerts_yaml=yaml)

    resp = client.post(
        "/alerts/rules/cpu_high/silence",
        json={"duration_seconds": 600},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rule_name"] == "cpu_high"
    assert body["silenced_until"]

    active = client.get("/alerts/active").json()
    assert "cpu_high" in active["silences"]

    resp = client.delete("/alerts/rules/cpu_high/silence")
    assert resp.status_code == 200
    active = client.get("/alerts/active").json()
    assert "cpu_high" not in active["silences"]


def test_alerts_silence_404_for_unknown_rule(tmp_path):
    yaml = """
rules:
  - name: cpu_high
    description: cpu
    severity: warning
    metric_path: system.cpu_percent
    comparator: ">"
    threshold: 80
""".strip()
    client = _make_client(tmp_path, alerts_yaml=yaml)
    resp = client.post("/alerts/rules/does_not_exist/silence", json={})
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ALERT_RULE_NOT_FOUND"


def test_evaluate_and_ack_full_flow(tmp_path):
    yaml = """
rules:
  - name: zero_messages_alert
    description: always-fire test rule (count of agent messages == 0)
    severity: warning
    metric_path: agent.message_count_total
    comparator: "=="
    threshold: 0
""".strip()
    client = _make_client(tmp_path, alerts_yaml=yaml)

    # Force a snapshot tick so the rule fires.
    task = client.app.state.snapshot_task
    asyncio.run(task.tick_once())

    active = client.get("/alerts/active").json()
    assert len(active["items"]) == 1
    event_id = active["items"][0]["id"]

    ack = client.post(f"/alerts/{event_id}/ack")
    assert ack.status_code == 200

    history = client.get("/alerts/history").json()
    assert any(item["id"] == event_id for item in history["items"])
