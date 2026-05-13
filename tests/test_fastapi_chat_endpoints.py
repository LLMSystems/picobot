import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient

from simplified_chatbot.agent.types import Message
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app


class _DummyResult:
    def __init__(self, *, messages: list[Message], content: str) -> None:
        self.messages = messages
        self.content = content
        self.model = "dummy"
        self.provider = "dummy"
        self.usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        self.tools_used = []
        self.stop_reason = "stop"


class _AsyncOnlyChatbot:
    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
    ) -> _DummyResult:
        history = history or []
        content = f"echo:{message}"
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": content},
        ]
        return _DummyResult(messages=messages, content=content)

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
    ) -> _DummyResult:
        if on_delta is not None:
            on_delta("echo:")
            on_delta(message)
        return await self.run_async(message, history=history)

    def run(self, message: str, history: list[Message] | None = None):
        raise AssertionError("sync run() should not be used")

    def run_stream(self, message: str, history: list[Message] | None = None, on_delta=None):
        raise AssertionError("sync run_stream() should not be used")


def test_post_chat_returns_full_response_and_persists_history(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hello"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "content": "echo:hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "tools_used": [],
        "stop_reason": "stop",
    }

    history = asyncio.run(store.load_history("s1"))
    assert history[-1] == {"role": "assistant", "content": "echo:hello"}


def test_get_chat_stream_returns_sse_events_and_persists_history(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/chat/stream",
        params={"session_id": "s1", "message": "hello"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: delta" in body
    assert "data: echo:" in body
    assert "data: hello" in body
    assert "event: done" in body

    done_payload = _extract_done_payload(body)
    assert done_payload == {
        "session_id": "s1",
        "content": "echo:hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "tools_used": [],
        "stop_reason": "stop",
    }

    history = asyncio.run(store.load_history("s1"))
    assert history[-1] == {"role": "assistant", "content": "echo:hello"}


def test_get_sessions_lists_persisted_sessions(tmp_path):
    client, _store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s2", "message": "hello"})
    client.post("/chat", json={"session_id": "s1", "message": "world"})

    response = client.get("/sessions")

    assert response.status_code == 200
    assert response.json() == {"sessions": ["s1", "s2"]}


def test_get_session_messages_returns_history(tmp_path):
    client, _store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s1", "message": "hello"})

    response = client.get("/sessions/s1/messages")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "messages": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "echo:hello"},
        ],
    }


def test_get_session_messages_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.get("/sessions/missing/messages")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session 'missing' not found"}


def test_delete_session_removes_history(tmp_path):
    client, store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s1", "message": "hello"})

    response = client.delete("/sessions/s1")

    assert response.status_code == 200
    assert response.json() == {"session_id": "s1", "deleted": True}
    assert asyncio.run(store.load_history("s1")) == []
    assert client.get("/sessions").json() == {"sessions": []}


def test_health_returns_ok():
    app = create_app(runtime=LocalAgentRuntime(chatbot=_AsyncOnlyChatbot()))
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _build_client(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    app = create_app(runtime=runtime)
    return TestClient(app), store


def _extract_done_payload(body: str) -> dict[str, object]:
    chunks = [chunk.strip() for chunk in body.split("\n\n") if chunk.strip()]
    for chunk in chunks:
        if not chunk.startswith("event: done"):
            continue
        data_lines = [line[6:] for line in chunk.splitlines() if line.startswith("data: ")]
        return json.loads("\n".join(data_lines))
    raise AssertionError("Missing SSE done event")
