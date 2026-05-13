import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient

from simplified_chatbot.agent.types import Message
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.app import create_app
from simplified_chatbot.tools.filesystem import build_default_tool_registry


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
        *,
        on_event=None,
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


class _EventfulToolChatbot:
    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ) -> _DummyResult:
        if on_event is not None:
            on_event(
                "tool_call_started",
                {
                    "id": "call_1",
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                },
            )
            on_event(
                "tool_call_finished",
                {
                    "id": "call_1",
                    "name": "read_file",
                    "ok": True,
                    "result": "1| hello\n2| world",
                },
            )
        if on_delta is not None:
            on_delta("done:")
            on_delta(message)
        history = history or []
        content = f"done:{message}"
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": content},
        ]
        result = _DummyResult(messages=messages, content=content)
        result.tools_used = ["read_file"]
        return result

    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event=None,
    ) -> _DummyResult:
        if on_event is not None:
            on_event(
                "tool_call_started",
                {
                    "id": "call_1",
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                },
            )
            on_event(
                "tool_call_finished",
                {
                    "id": "call_1",
                    "name": "read_file",
                    "ok": True,
                    "result": "1| hello\n2| world",
                },
            )
        history = history or []
        content = f"done:{message}"
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": content},
        ]
        result = _DummyResult(messages=messages, content=content)
        result.tools_used = ["read_file"]
        return result

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() should not be used")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() should not be used")


class _CapabilityChatbot(_AsyncOnlyChatbot):
    def __init__(self, tmp_path) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-4.1-mini",
            max_iterations=8,
        )
        self.tools = build_default_tool_registry(workspace=tmp_path)


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
    assert response.headers["x-request-id"].startswith("req_")
    assert response.json() == {
        "session_id": "s1",
        "content": "echo:hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "tools_used": [],
        "stop_reason": "stop",
        "events": [
            {
                "event": "run_started",
                "data": {"session_id": "s1", "message": "hello"},
            },
        ],
    }

    history = asyncio.run(store.load_history("s1"))
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "echo:hello"
    assert history[-1]["id"].startswith("msg_")
    assert history[-1]["created_at"].endswith("Z")


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
    assert "event: run_started" in body
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
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "echo:hello"
    assert history[-1]["id"].startswith("msg_")
    assert history[-1]["created_at"].endswith("Z")


def test_post_chat_stream_returns_sse_events_and_persists_history(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": "s1", "message": "hello"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: run_started" in body
    assert "event: delta" in body
    assert "event: done" in body

    done_payload = _extract_done_payload(body)
    assert done_payload == {
        "session_id": "s1",
        "content": "echo:hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "tools_used": [],
        "stop_reason": "stop",
    }


def test_get_chat_stream_emits_tool_events(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_EventfulToolChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/chat/stream",
        params={"session_id": "s1", "message": "hello"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: run_started" in body
    assert "event: tool_call_started" in body
    assert "event: tool_call_finished" in body
    assert '"name": "read_file"' in body
    assert '"ok": true' in body
    assert '1| hello\\n2| world' in body
    assert "event: done" in body


def test_post_chat_returns_trace_events(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_EventfulToolChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hello"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    assert response.json() == {
        "session_id": "s1",
        "content": "done:hello",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        "tools_used": ["read_file"],
        "stop_reason": "stop",
        "events": [
            {
                "event": "run_started",
                "data": {"session_id": "s1", "message": "hello"},
            },
            {
                "event": "tool_call_started",
                "data": {
                    "id": "call_1",
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                },
            },
            {
                "event": "tool_call_finished",
                "data": {
                    "id": "call_1",
                    "name": "read_file",
                    "ok": True,
                    "result": "1| hello\n2| world",
                },
            },
        ],
    }


def test_get_sessions_lists_persisted_sessions(tmp_path):
    client, _store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s2", "message": "hello"})
    client.post("/chat", json={"session_id": "s1", "message": "world"})

    response = client.get("/sessions")

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    payload = response.json()
    assert payload["sessions"][0]["session_id"] == "s1"
    assert payload["sessions"][1]["session_id"] == "s2"
    assert payload["sessions"][0]["title"] == "world"
    assert payload["sessions"][0]["message_count"] == 2
    assert payload["sessions"][0]["last_user_message"] == "world"
    assert payload["sessions"][0]["last_assistant_preview"] == "echo:world"
    assert isinstance(payload["sessions"][0]["created_at"], str)
    assert isinstance(payload["sessions"][0]["updated_at"], str)


def test_post_sessions_creates_empty_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.post("/sessions", json={"title": "Plan next step"})

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    payload = response.json()
    assert payload["session_id"].startswith("session_")
    assert payload["title"] == "Plan next step"
    assert payload["message_count"] == 0
    assert payload["last_user_message"] == ""
    assert payload["last_assistant_preview"] == ""
    assert isinstance(payload["created_at"], str)
    assert isinstance(payload["updated_at"], str)


def test_patch_session_renames_existing_session(tmp_path):
    client, _store = _build_client(tmp_path)
    created = client.post(
        "/sessions",
        json={"title": "Old title", "session_id": "s1"},
    )
    assert created.status_code == 200

    response = client.patch("/sessions/s1", json={"title": "New title"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "s1"
    assert payload["title"] == "New title"
    assert payload["message_count"] == 0
    assert isinstance(payload["updated_at"], str)


def test_get_capabilities_returns_frontend_metadata(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(
        chatbot=_CapabilityChatbot(tmp_path),
        store=store,
        workspace_root_dir=tmp_path / "workspaces",
    )
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req_")
    payload = response.json()
    assert payload["model"] == {
        "provider": "openai_compat",
        "name": "gpt-4.1-mini",
    }
    assert payload["max_iterations"] == 8
    assert payload["features"] == {
        "streaming": True,
        "session_workspace": True,
        "file_upload": False,
        "multimodal": False,
    }
    tools = {item["name"]: item for item in payload["tools"]}
    assert tools["read_file"]["category"] == "filesystem"
    assert tools["read_file"]["dangerous"] is False
    assert tools["exec"]["category"] == "shell"
    assert tools["exec"]["dangerous"] is True


def test_get_session_messages_returns_history(tmp_path):
    client, _store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s1", "message": "hello"})

    response = client.get("/sessions/s1/messages")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "messages": response.json()["messages"],
    }
    assert response.json()["messages"][0]["role"] == "user"
    assert response.json()["messages"][0]["content"] == "hello"
    assert response.json()["messages"][0]["id"].startswith("msg_")
    assert response.json()["messages"][0]["created_at"].endswith("Z")
    assert response.json()["messages"][1]["role"] == "assistant"
    assert response.json()["messages"][1]["content"] == "echo:hello"
    assert response.json()["messages"][1]["id"].startswith("msg_")
    assert response.json()["messages"][1]["created_at"].endswith("Z")


def test_get_session_messages_returns_empty_list_for_created_session(tmp_path):
    client, _store = _build_client(tmp_path)
    created = client.post(
        "/sessions",
        json={"title": "Empty session", "session_id": "s1"},
    )
    assert created.status_code == 200

    response = client.get("/sessions/s1/messages")

    assert response.status_code == 200
    assert response.json() == {"session_id": "s1", "messages": []}


def test_get_session_messages_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.get("/sessions/missing/messages")

    assert response.status_code == 404
    assert response.headers["x-request-id"].startswith("req_")
    assert response.json() == {
        "error": {
            "code": "SESSION_NOT_FOUND",
            "message": "Session 'missing' not found",
            "request_id": response.headers["x-request-id"],
        },
    }


def test_delete_session_removes_history(tmp_path):
    client, store = _build_client(tmp_path)

    client.post("/chat", json={"session_id": "s1", "message": "hello"})

    response = client.delete("/sessions/s1")

    assert response.status_code == 200
    assert response.json() == {"session_id": "s1", "deleted": True}
    assert asyncio.run(store.load_history("s1")) == []
    assert client.get("/sessions").json() == {"sessions": []}


def test_patch_session_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.patch("/sessions/missing", json={"title": "Still missing"})

    assert response.status_code == 404
    assert response.headers["x-request-id"].startswith("req_")
    assert response.json() == {
        "error": {
            "code": "SESSION_NOT_FOUND",
            "message": "Session 'missing' not found",
            "request_id": response.headers["x-request-id"],
        },
    }


def test_post_chat_returns_structured_validation_error(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.post("/chat", json={"session_id": "s1", "message": ""})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "MESSAGE_INVALID",
            "message": "message must not be empty",
            "request_id": response.headers["x-request-id"],
        },
    }


def test_post_chat_stream_returns_structured_validation_error(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.post("/chat/stream", json={"session_id": "s1", "message": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


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
