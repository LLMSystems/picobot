import asyncio

import pytest

pytest.importorskip("fastapi")

from starlette.requests import Request

from simplified_chatbot.alerts.events_store import AlertEventRow
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.server.app import create_app
from simplified_chatbot.server import endpoints_alerts


class _DummyChatbot:
    def __init__(self) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
        )


class _FakeAlertsService:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.rules = []
        self.unsubscribed = False

    async def list_active(self):
        return [
            AlertEventRow(
                id=1,
                rule_name="cpu_high",
                severity="warning",
                description="CPU usage is high",
                metric_path="system.cpu_percent",
                comparator=">",
                threshold="80",
                fired_at="2026-06-03T10:00:00+00:00",
                resolved_at=None,
                acknowledged_at=None,
                trigger_value=91.2,
                context={"host": "local"},
            ),
        ]

    async def list_silences(self):
        return {"cpu_high": "2026-06-03T11:00:00+00:00"}

    def subscribe(self):
        return self._queue

    def unsubscribe(self, queue):
        assert queue is self._queue
        self.unsubscribed = True

    def display_name_for(self, rule_name: str):
        return "CPU High" if rule_name == "cpu_high" else None


def _build_request(app):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/alerts/stream",
        "headers": [],
        "query_string": b"",
        "app": app,
        "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_alerts_stream_returns_snapshot_and_live_event(tmp_path):
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot())
    app = create_app(runtime=runtime)
    fake = _FakeAlertsService()
    fake._queue.put_nowait(
        {
            "event": "alert_fired",
            "data": {"rule_name": "cpu_high", "event_id": 1},
        },
    )
    app.state.alerts = fake

    async def scenario() -> tuple[bytes, bytes]:
        response = await endpoints_alerts.alerts_stream(_build_request(app))
        iterator = response.body_iterator
        first = await anext(iterator)
        second = await anext(iterator)
        await iterator.aclose()
        return first, second

    first, second = asyncio.run(scenario())

    assert "event: alert_snapshot" in first.decode("utf-8")
    assert '"display_name": "CPU High"' in first.decode("utf-8")
    assert '"cpu_high": "2026-06-03T11:00:00+00:00"' in first.decode("utf-8")
    assert "event: alert_fired" in second.decode("utf-8")
    assert '"event_id": 1' in second.decode("utf-8")
    assert fake.unsubscribed is True


def test_alerts_stream_returns_503_when_service_is_disabled(tmp_path):
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot())
    app = create_app(runtime=runtime)
    app.state.alerts = None

    response = asyncio.run(endpoints_alerts.alerts_stream(_build_request(app)))

    assert response.status_code == 503
    assert b"ALERTS_DISABLED" in response.body
