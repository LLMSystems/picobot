import asyncio
import json
from pathlib import Path

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


class _MemoryConfigChatbot(_AsyncOnlyChatbot):
    def __init__(self) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-4.1-mini",
            memory_enabled=True,
        )


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


class _ReasoningChatbot:
    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ) -> _DummyResult:
        if on_event is not None:
            on_event("reasoning_delta", {"delta": "先想"})
        if on_delta is not None:
            on_delta("done:")
            on_delta(message)
        history = history or []
        content = f"done:{message}"
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": content,
                "metadata": {"reasoning_content": "先想"},
            },
        ]
        return _DummyResult(messages=messages, content=content)

    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event=None,
    ) -> _DummyResult:
        if on_event is not None:
            on_event("reasoning_delta", {"delta": "先想"})
        history = history or []
        content = f"done:{message}"
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {
                "role": "assistant",
                "content": content,
                "metadata": {"reasoning_content": "先想"},
            },
        ]
        return _DummyResult(messages=messages, content=content)

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() should not be used")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() should not be used")


class _CapabilityChatbot(_AsyncOnlyChatbot):
    def __init__(self, tmp_path) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-4.1-mini",
            available_models=["gpt-4.1-mini", "gpt-5-mini"],
            max_iterations=8,
        )
        self.tools = build_default_tool_registry(workspace=tmp_path)


class _WriteEventfulToolChatbot:
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
                    "name": "write_file",
                    "arguments": {"path": "doc/design.md", "content": "# Design\n"},
                },
            )
            on_event(
                "tool_call_finished",
                {
                    "id": "call_1",
                    "name": "write_file",
                    "ok": True,
                    "result": "Successfully wrote 9 characters to doc/design.md",
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
        result.tools_used = ["write_file"]
        return result

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ) -> _DummyResult:
        if on_delta is not None:
            on_delta("done:")
            on_delta(message)
        return await self.run_async(message, history=history, on_event=on_event)

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() should not be used")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() should not be used")


class _ModelAwareChatbot(_AsyncOnlyChatbot):
    def __init__(self) -> None:
        self.calls: list[str | None] = []
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-4.1-mini",
            available_models=["gpt-4.1-mini", "gpt-5-mini"],
            max_iterations=8,
        )
        self.tools = build_default_tool_registry(workspace=Path.cwd())

    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        model_override=None,
        on_event=None,
    ) -> _DummyResult:
        self.calls.append(model_override)
        result = await super().run_async(message, history=history, on_event=on_event)
        result.model = model_override or self.config.model
        return result

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        model_override=None,
        on_event=None,
    ) -> _DummyResult:
        self.calls.append(model_override)
        if on_delta is not None:
            on_delta("echo:")
            on_delta(message)
        result = await super().run_async(message, history=history, on_event=on_event)
        result.model = model_override or self.config.model
        return result


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


def test_post_chat_accepts_model_override(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    chatbot = _ModelAwareChatbot()
    runtime = LocalAgentRuntime(chatbot=chatbot, store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hello", "model": "gpt-5-mini"},
    )

    assert response.status_code == 200
    assert response.json()["content"] == "echo:hello"
    assert chatbot.calls == ["gpt-5-mini"]


def test_post_chat_rejects_model_outside_allowlist(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    chatbot = _ModelAwareChatbot()
    runtime = LocalAgentRuntime(chatbot=chatbot, store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hello", "model": "gpt-unknown"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MODEL_NOT_ALLOWED"


def test_cors_preflight_returns_expected_headers(tmp_path, monkeypatch):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://picobot.zeabur.app")
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.options(
        "/capabilities",
        headers={
            "Origin": "https://picobot.zeabur.app",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://picobot.zeabur.app"
    )
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_actual_request_returns_allow_origin_header(tmp_path, monkeypatch):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=store)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://picobot.zeabur.app")
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.get(
        "/health",
        headers={"Origin": "https://picobot.zeabur.app"},
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://picobot.zeabur.app"
    )


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


def test_post_chat_stream_accepts_model_override(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    chatbot = _ModelAwareChatbot()
    runtime = LocalAgentRuntime(chatbot=chatbot, store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "POST",
        "/chat/stream",
        json={"session_id": "s1", "message": "hello", "model": "gpt-5-mini"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: done" in body
    assert chatbot.calls == ["gpt-5-mini"]


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


def test_get_chat_stream_emits_reasoning_events_and_persists_metadata(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_ReasoningChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/chat/stream",
        params={"session_id": "s1", "message": "hello"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: reasoning_delta" in body
    assert '"delta": "先想"' in body
    history = asyncio.run(store.load_history("s1"))
    assert history[-1]["metadata"] == {"reasoning_content": "先想"}


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


def test_post_chat_returns_reasoning_trace_events(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_ReasoningChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"session_id": "s1", "message": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["events"] == [
        {
            "event": "run_started",
            "data": {"session_id": "s1", "message": "hello"},
        },
        {
            "event": "reasoning_delta",
            "data": {"delta": "先想"},
        },
    ]


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
    assert payload["available_models"] == ["gpt-4.1-mini", "gpt-5-mini"]
    assert payload["max_iterations"] == 8
    assert payload["features"] == {
        "streaming": True,
        "session_workspace": True,
        "file_upload": True,
        "multimodal": True,
        "model_override": True,
    }
    tools = {item["name"]: item for item in payload["tools"]}
    assert tools["read_file"]["category"] == "filesystem"
    assert tools["read_file"]["dangerous"] is False
    assert tools["exec"]["category"] == "shell"
    assert tools["exec"]["dangerous"] is True


def test_get_workspace_tree_returns_entries(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    client.post("/sessions", json={"title": "Workspace", "session_id": "s1"})
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "doc").mkdir()
    (workspace / "doc" / "design.md").write_text("# Design\n", encoding="utf-8")

    response = client.get("/sessions/s1/workspace/tree", params={"recursive": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "s1"
    assert payload["path"] == "."
    paths = {entry["path"] for entry in payload["entries"]}
    assert "doc" in paths
    assert "doc/design.md" in paths
    for entry in payload["entries"]:
        assert isinstance(entry["updated_at"], str)
        assert entry["updated_at"].endswith("Z")
    assert payload["truncated"] is False


def test_get_workspace_file_returns_utf8_content(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    client.post("/sessions", json={"title": "Workspace", "session_id": "s1"})
    workspace = runtime.workspace_manager.ensure_workspace("s1")
    (workspace / "doc").mkdir()
    (workspace / "doc" / "design.md").write_text("# Design\n\nHello\n", encoding="utf-8")

    response = client.get(
        "/sessions/s1/workspace/file",
        params={"path": "doc/design.md"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "path": "doc/design.md",
        "content": "# Design\n\nHello\n",
        "encoding": "utf-8",
        "truncated": False,
        "line_count": 3,
    }


def test_get_workspace_file_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.get("/sessions/missing/workspace/file", params={"path": "doc/design.md"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_get_workspace_file_rejects_path_traversal(tmp_path):
    client, _runtime, _store = _build_client(tmp_path, with_runtime=True)
    client.post("/sessions", json={"title": "Workspace", "session_id": "s1"})

    response = client.get("/sessions/s1/workspace/file", params={"path": "../secret.txt"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WORKSPACE_PATH_INVALID"


def test_post_chat_trace_includes_workspace_changed(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_WriteEventfulToolChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    response = client.post("/chat", json={"session_id": "s1", "message": "write it"})

    assert response.status_code == 200
    events = response.json()["events"]
    assert {
        "event": "workspace_changed",
        "data": {"session_id": "s1", "paths": ["doc/design.md"]},
    } in events


def test_stream_emits_workspace_changed_event(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_WriteEventfulToolChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    with client.stream(
        "GET",
        "/chat/stream",
        params={"session_id": "s1", "message": "write it"},
    ) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: workspace_changed" in body
    assert '"session_id": "s1"' in body
    assert '"paths": ["doc/design.md"]' in body


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


def test_get_session_memory_returns_summary(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200
    assert runtime.memory_store is not None
    asyncio.run(
        runtime.memory_store.save_memory(
            "s1",
            summary="- User prefers concise answers\n- Project uses AioSQLite",
            compacted_message_count=12,
        ),
    )

    response = client.get("/sessions/s1/memory")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "enabled": True,
        "has_summary": True,
        "summary": "- User prefers concise answers\n- Project uses AioSQLite",
        "compacted_message_count": 12,
        "updated_at": response.json()["updated_at"],
        "notes": [],
    }
    assert response.json()["updated_at"].endswith("Z")


def test_get_session_memory_includes_user_notes(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200
    assert runtime.memory_store is not None
    asyncio.run(
        runtime.memory_store.add_note(
            "s1",
            kind="preference",
            content="Prefer Traditional Chinese responses",
        ),
    )

    response = client.get("/sessions/s1/memory")

    assert response.status_code == 200
    assert response.json()["notes"] == [
        {
            "id": response.json()["notes"][0]["id"],
            "session_id": "s1",
            "kind": "preference",
            "content": "Prefer Traditional Chinese responses",
            "created_at": response.json()["notes"][0]["created_at"],
            "updated_at": response.json()["notes"][0]["updated_at"],
        },
    ]


def test_get_session_memory_returns_empty_payload_before_compaction(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200

    response = client.get("/sessions/s1/memory")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "enabled": True,
        "has_summary": False,
        "summary": "",
        "compacted_message_count": 0,
        "updated_at": None,
        "notes": [],
    }


def test_get_session_memory_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.get("/sessions/missing/memory")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_create_session_memory_note(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200

    response = client.post(
        "/sessions/s1/memory/notes",
        json={
            "kind": "correction",
            "content": "Picobot and Nanobot are separate projects",
        },
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "s1"
    assert response.json()["kind"] == "correction"
    assert response.json()["content"] == "Picobot and Nanobot are separate projects"


def test_delete_session_memory_note_archives_it(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200
    assert runtime.memory_store is not None
    note = asyncio.run(
        runtime.memory_store.add_note(
            "s1",
            kind="note",
            content="Remember the deployment checklist",
        ),
    )

    response = client.delete(f"/sessions/s1/memory/notes/{note.id}")
    memory_response = client.get("/sessions/s1/memory")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "s1",
        "note_id": note.id,
        "deleted": True,
    }
    assert memory_response.status_code == 200
    assert memory_response.json()["notes"] == []


def test_clear_session_memory_summary_keeps_notes(tmp_path):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(chatbot=_MemoryConfigChatbot(), store=store)
    app = create_app(runtime=runtime)
    client = TestClient(app)

    created = client.post(
        "/sessions",
        json={"title": "Memory session", "session_id": "s1"},
    )
    assert created.status_code == 200
    assert runtime.memory_store is not None
    asyncio.run(
        runtime.memory_store.save_memory(
            "s1",
            summary="- User prefers concise answers\n- Project uses AioSQLite",
            compacted_message_count=12,
        ),
    )
    asyncio.run(
        runtime.memory_store.add_note(
            "s1",
            kind="preference",
            content="Prefer Traditional Chinese responses",
        ),
    )

    response = client.delete("/sessions/s1/memory/summary")

    assert response.status_code == 200
    assert response.json()["has_summary"] is False
    assert response.json()["summary"] == ""
    assert response.json()["compacted_message_count"] == 0
    assert len(response.json()["notes"]) == 1
    assert response.json()["notes"][0]["content"] == "Prefer Traditional Chinese responses"


def test_get_session_events_stream_returns_404_for_unknown_session(tmp_path):
    client, _store = _build_client(tmp_path)

    response = client.get("/sessions/missing/events/stream")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_get_session_events_stream_emits_live_subagent_event_and_unsubscribes(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    created = client.post(
        "/sessions",
        json={"title": "Live session", "session_id": "sse1"},
    )
    assert created.status_code == 200

    preloaded: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    preloaded.put_nowait(
        {
            "session_id": "sse1",
            "task_id": "sub_1234",
            "label": "collect refs",
            "event": "subagent_delta",
            "data": {"delta": "Scanning files..."},
            "seq": 1,
            "created_at": "2026-05-27T12:00:00Z",
        },
    )
    preloaded.put_nowait({"event": "__close__"})

    calls: dict[str, object] = {"unsubscribed": False}

    def fake_subscribe(session_id: str):
        assert session_id == "sse1"
        return preloaded

    def fake_unsubscribe(session_id: str, queue):
        assert session_id == "sse1"
        assert queue is preloaded
        calls["unsubscribed"] = True

    runtime.subscribe_session_events = fake_subscribe  # type: ignore[method-assign]
    runtime.unsubscribe_session_events = fake_unsubscribe  # type: ignore[method-assign]

    with client.stream("GET", "/sessions/sse1/events/stream") as response:
        iterator = response.iter_text()
        first_chunk = next(iterator)

    assert response.status_code == 200
    assert "event: subagent_delta" in first_chunk
    assert '"session_id": "sse1"' in first_chunk
    assert '"task_id": "sub_1234"' in first_chunk
    assert '"delta": "Scanning files..."' in first_chunk
    assert calls["unsubscribed"] is True


def test_get_session_subagents_lists_persisted_runs(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    created = client.post(
        "/sessions",
        json={"title": "Reload session", "session_id": "subsess1"},
    )
    assert created.status_code == 200
    asyncio.run(
        runtime.subagent_store.upsert_run(
            {
                "task_id": "sub_1",
                "parent_session_id": "subsess1",
                "label": "collect refs",
                "task": "Collect references",
                "workspace": "D:/tmp/sub_1",
                "phase": "done",
                "started_at": "2026-05-27T12:00:00Z",
                "finished_at": "2026-05-27T12:00:10Z",
                "stop_reason": "stop",
                "ok": True,
                "error": None,
                "usage": {"prompt_tokens": 10},
                "tool_events": [],
                "final_content": "done",
            },
        ),
    )

    response = client.get("/sessions/subsess1/subagents")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "subsess1",
        "items": [
            {
                "task_id": "sub_1",
                "parent_session_id": "subsess1",
                "label": "collect refs",
                "task": "Collect references",
                "workspace": "D:/tmp/sub_1",
                "phase": "done",
                "started_at": "2026-05-27T12:00:00Z",
                "finished_at": "2026-05-27T12:00:10Z",
                "stop_reason": "stop",
                "ok": True,
                "error": None,
                "usage": {"prompt_tokens": 10},
                "tool_events": [],
                "final_content": "done",
                "model": None,
            },
        ],
    }


def test_get_session_subagent_returns_single_persisted_run(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    created = client.post(
        "/sessions",
        json={"title": "Reload session", "session_id": "subsess2"},
    )
    assert created.status_code == 200
    asyncio.run(
        runtime.subagent_store.upsert_run(
            {
                "task_id": "sub_2",
                "parent_session_id": "subsess2",
                "label": "scan",
                "task": "Scan repository",
                "workspace": None,
                "phase": "running",
                "started_at": "2026-05-27T12:01:00Z",
                "finished_at": None,
                "stop_reason": None,
                "ok": None,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": None,
            },
        ),
    )

    response = client.get("/sessions/subsess2/subagents/sub_2")

    assert response.status_code == 200
    assert response.json()["task_id"] == "sub_2"
    assert response.json()["parent_session_id"] == "subsess2"
    assert response.json()["phase"] == "running"


def test_get_session_subagent_events_returns_persisted_timeline(tmp_path):
    client, runtime, _store = _build_client(tmp_path, with_runtime=True)
    created = client.post(
        "/sessions",
        json={"title": "Reload session", "session_id": "subsess3"},
    )
    assert created.status_code == 200
    asyncio.run(
        runtime.subagent_store.upsert_run(
            {
                "task_id": "sub_3",
                "parent_session_id": "subsess3",
                "label": "stream",
                "task": "Stream task",
                "workspace": None,
                "phase": "done",
                "started_at": "2026-05-27T12:02:00Z",
                "finished_at": "2026-05-27T12:02:10Z",
                "stop_reason": "completed",
                "ok": True,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": "done",
            },
        ),
    )
    asyncio.run(
        runtime.subagent_event_store.append_event(
            task_id="sub_3",
            parent_session_id="subsess3",
            event_type="subagent_spawned",
            payload={"label": "stream", "data": {"task": "Stream task"}},
            created_at="2026-05-27T12:02:00Z",
        ),
    )
    asyncio.run(
        runtime.subagent_event_store.append_event(
            task_id="sub_3",
            parent_session_id="subsess3",
            event_type="subagent_completed",
            payload={"label": "stream", "data": {"ok": True}},
            created_at="2026-05-27T12:02:10Z",
        ),
    )

    response = client.get("/sessions/subsess3/subagents/sub_3/events")

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "subsess3",
        "task_id": "sub_3",
        "events": [
            {
                "id": 1,
                "task_id": "sub_3",
                "parent_session_id": "subsess3",
                "seq": 1,
                "event_type": "subagent_spawned",
                "created_at": "2026-05-27T12:02:00Z",
                "payload": {"label": "stream", "data": {"task": "Stream task"}},
            },
            {
                "id": 2,
                "task_id": "sub_3",
                "parent_session_id": "subsess3",
                "seq": 2,
                "event_type": "subagent_completed",
                "created_at": "2026-05-27T12:02:10Z",
                "payload": {"label": "stream", "data": {"ok": True}},
            },
        ],
    }


def test_get_session_subagent_returns_404_for_missing_task(tmp_path):
    client, _runtime, _store = _build_client(tmp_path, with_runtime=True)
    created = client.post(
        "/sessions",
        json={"title": "Reload session", "session_id": "subsess4"},
    )
    assert created.status_code == 200

    response = client.get("/sessions/subsess4/subagents/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SUBAGENT_NOT_FOUND"


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

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


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


def _build_client(tmp_path, *, with_runtime: bool = False):
    store = AioSQLiteSessionStore(tmp_path / "sessions.db")
    runtime = LocalAgentRuntime(
        chatbot=_AsyncOnlyChatbot(),
        store=store,
        workspace_root_dir=tmp_path / "workspaces",
    )
    app = create_app(runtime=runtime)
    client = TestClient(app)
    if with_runtime:
        return client, runtime, store
    return client, store


def _extract_done_payload(body: str) -> dict[str, object]:
    chunks = [chunk.strip() for chunk in body.split("\n\n") if chunk.strip()]
    for chunk in chunks:
        if not chunk.startswith("event: done"):
            continue
        data_lines = [line[6:] for line in chunk.splitlines() if line.startswith("data: ")]
        return json.loads("\n".join(data_lines))
    raise AssertionError("Missing SSE done event")
