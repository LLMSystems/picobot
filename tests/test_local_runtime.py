import asyncio
import json
from pathlib import Path

from simplified_chatbot.agent.types import Message, MessageContent
from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ProviderResponse, ToolCallRequest
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import (
    AsyncSessionStore,
    InMemorySessionStore,
    JsonlSessionStore,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager
from simplified_chatbot.tools.filesystem import build_default_tool_registry


class _DummyChatbot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[Message]]] = []
        self.async_calls: list[str] = []

    def run(self, message: str, history: list[Message] | None = None):
        history = history or []
        self.calls.append((message, history))
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"echo:{message}"},
        ]
        return _DummyResult(messages=messages, content=f"echo:{message}")

    def run_stream(self, message: str, history: list[Message] | None = None, on_delta=None):
        if on_delta is not None:
            on_delta("echo:")
            on_delta(message)
        return self.run(message, history=history)

    async def run_async(self, message: str, history: list[Message] | None = None):
        self.async_calls.append("run_async")
        return self.run(message, history=history)

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        on_delta=None,
    ):
        self.async_calls.append("run_stream_async")
        return self.run_stream(message, history=history, on_delta=on_delta)


class _DummyResult:
    def __init__(self, *, messages: list[Message], content: str) -> None:
        self.messages = messages
        self.content = content
        self.model = "dummy"
        self.provider = "dummy"
        self.usage = {}
        self.tools_used = []
        self.stop_reason = "stop"


class _MultimodalEchoChatbot:
    def __init__(self) -> None:
        self.calls: list[MessageContent] = []
        self.events: list[tuple[str, dict[str, object]]] = []

    async def run_async(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        on_event=None,
    ):
        history = history or []
        self.calls.append(message)
        if on_event is not None:
            on_event("custom", {"kind": "multimodal"})
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": "multimodal-ok"},
        ]
        return _DummyResult(messages=messages, content="multimodal-ok")

    async def run_stream_async(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        on_delta=None,
        on_event=None,
    ):
        if on_delta is not None:
            on_delta("multimodal-")
            on_delta("ok")
        return await self.run_async(message, history=history, on_event=on_event)

    def run(self, *args, **kwargs):
        raise AssertionError("sync run() should not be called")

    def run_stream(self, *args, **kwargs):
        raise AssertionError("sync run_stream() should not be called")


class _AsyncOnlyChatbot:
    async def run_async(self, message: str, history: list[Message] | None = None):
        history = history or []
        messages: list[Message] = [
            *history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": f"async:{message}"},
        ]
        return _DummyResult(messages=messages, content=f"async:{message}")

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        on_delta=None,
    ):
        if on_delta is not None:
            on_delta("async:")
            on_delta(message)
        return await self.run_async(message, history=history)

    def run(self, message: str, history: list[Message] | None = None):
        raise AssertionError("sync run() should not be called")

    def run_stream(self, message: str, history: list[Message] | None = None, on_delta=None):
        raise AssertionError("sync run_stream() should not be called")


class _DummyAsyncStore(AsyncSessionStore):
    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}

    async def load_history(self, session_id: str) -> list[Message]:
        return [dict(item) for item in self._sessions.get(session_id, [])]

    async def save_history(self, session_id: str, history: list[Message]) -> None:
        self._sessions[session_id] = [dict(item) for item in history]

    async def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def list_sessions(self) -> list[str]:
        return sorted(self._sessions.keys())


class _ReadWorkspaceProvider:
    async def generate_async(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        if messages[-1]["role"] == "user":
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_read_1",
                        name="read_file",
                        arguments={"path": "notes.txt"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        return ProviderResponse(
            content=messages[-1]["content"],
            finish_reason="stop",
        )

    async def stream_generate_async(self, *args, **kwargs):
        raise AssertionError("stream_generate_async should not be called in this test")


class _WriteWorkspaceProvider:
    async def generate_async(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        if messages[-1]["role"] == "user":
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_write_1",
                        name="write_file",
                        arguments={"path": "doc/design.md", "content": "# Design\n"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        return ProviderResponse(content="Wrote the file.", finish_reason="stop")

    async def stream_generate_async(self, *args, **kwargs):
        raise AssertionError("stream_generate_async should not be called in this test")


class _ExecWorkspaceProvider:
    async def generate_async(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        if messages[-1]["role"] == "user":
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_exec_1",
                        name="exec",
                        arguments={"command": "echo hello"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        return ProviderResponse(content="Ran command.", finish_reason="stop")

    async def stream_generate_async(self, *args, **kwargs):
        raise AssertionError("stream_generate_async should not be called in this test")


def test_local_runtime_uses_existing_history_and_persists_new_turn():
    bot = _DummyChatbot()
    store = InMemorySessionStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)

    r1 = runtime.handle_message("s1", "hello")
    r2 = runtime.handle_message("s1", "again")

    assert r1.content == "echo:hello"
    assert r2.content == "echo:again"
    assert len(bot.calls[1][1]) == 2
    assert store.load_history("s1")[-1]["content"] == "echo:again"
    assert store.load_history("s1")[-1]["id"].startswith("msg_")
    assert store.load_history("s1")[-1]["created_at"].endswith("Z")


def test_local_runtime_stream_persists_history():
    bot = _DummyChatbot()
    store = InMemorySessionStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)
    deltas: list[str] = []

    result = runtime.handle_message_stream("s1", "hello", on_delta=deltas.append)

    assert result.content == "echo:hello"
    assert deltas == ["echo:", "hello"]
    assert store.load_history("s1")[-1]["content"] == "echo:hello"
    assert store.load_history("s1")[-1]["id"].startswith("msg_")
    assert store.load_history("s1")[-1]["created_at"].endswith("Z")


def test_local_runtime_with_jsonl_store_persists_to_files(tmp_path: Path):
    bot = _DummyChatbot()
    store = JsonlSessionStore(tmp_path / "sessions")
    runtime = LocalAgentRuntime(chatbot=bot, store=store)

    runtime.handle_message("chat-a", "hello")

    files = list((tmp_path / "sessions").glob("*.jsonl"))
    assert len(files) == 1
    assert store.load_history("chat-a")[-1]["content"] == "echo:hello"


def test_local_runtime_async_methods_with_async_store():
    bot = _DummyChatbot()
    store = _DummyAsyncStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)
    deltas: list[str] = []

    result = asyncio.run(runtime.handle_message_async("s1", "hello"))
    streamed = asyncio.run(
        runtime.handle_message_stream_async("s1", "again", on_delta=deltas.append),
    )
    sessions = asyncio.run(runtime.list_sessions_async())
    asyncio.run(runtime.reset_session_async("s1"))
    sessions_after = asyncio.run(runtime.list_sessions_async())

    assert result.content == "echo:hello"
    assert streamed.content == "echo:again"
    assert deltas == ["echo:", "again"]
    assert sessions == ["s1"]
    assert sessions_after == []
    assert bot.async_calls == ["run_async", "run_stream_async"]


def test_local_runtime_sync_methods_reject_async_store():
    bot = _DummyChatbot()
    store = _DummyAsyncStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)

    try:
        runtime.handle_message("s1", "hello")
    except RuntimeError as exc:
        assert "handle_message_async" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when using sync API with AsyncSessionStore")


def test_local_runtime_async_with_sync_store_prefers_async_chatbot():
    bot = _AsyncOnlyChatbot()
    store = InMemorySessionStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)
    deltas: list[str] = []

    result = asyncio.run(runtime.handle_message_async("s1", "hello"))
    streamed = asyncio.run(
        runtime.handle_message_stream_async("s1", "again", on_delta=deltas.append),
    )
    sessions = asyncio.run(runtime.list_sessions_async())

    assert result.content == "async:hello"
    assert streamed.content == "async:again"
    assert deltas == ["async:", "again"]
    assert sessions == ["s1"]


def test_local_runtime_handle_input_async_accepts_multimodal_content():
    bot = _MultimodalEchoChatbot()
    store = InMemorySessionStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)
    content: MessageContent = [
        {"type": "text", "text": "Describe this image"},
        {"type": "image", "url": "https://example.com/cat.png", "detail": "high"},
    ]
    events: list[tuple[str, dict[str, object]]] = []

    result = asyncio.run(
        runtime.handle_input_async(
            "s1",
            content,
            on_event=lambda event, data: events.append((event, data)),
        ),
    )

    assert result.content == "multimodal-ok"
    assert bot.calls == [content]
    assert events[0] == (
        "run_started",
        {
            "session_id": "s1",
            "message": "Describe this image\n[image]",
            "content": content,
        },
    )
    assert events[1] == ("custom", {"kind": "multimodal"})
    history = store.load_history("s1")
    assert history[0]["content"] == content
    assert history[1]["content"] == "multimodal-ok"


def test_local_runtime_handle_input_stream_async_accepts_multimodal_content():
    bot = _MultimodalEchoChatbot()
    store = InMemorySessionStore()
    runtime = LocalAgentRuntime(chatbot=bot, store=store)
    content: MessageContent = [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image", "url": "https://example.com/dog.png"},
    ]
    deltas: list[str] = []

    result = asyncio.run(
        runtime.handle_input_stream_async(
            "s1",
            content,
            on_delta=deltas.append,
        ),
    )

    assert result.content == "multimodal-ok"
    assert bot.calls == [content]
    assert deltas == ["multimodal-", "ok"]


def test_local_runtime_create_and_rename_session():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())

    created = runtime.create_session(title="Plan this", session_id="s1")
    renamed = runtime.rename_session("s1", "Renamed title")

    assert created["session_id"] == "s1"
    assert created["title"] == "Plan this"
    assert created["message_count"] == 0
    assert isinstance(created["created_at"], str)
    assert isinstance(created["updated_at"], str)
    assert renamed["title"] == "Renamed title"


def test_local_runtime_session_summary_uses_multimodal_preview():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())
    history: list[Message] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Review this screenshot"},
                {"type": "image", "url": "https://example.com/s1.png"},
            ],
        },
        {"role": "assistant", "content": "Looks good"},
    ]

    summary = runtime._build_session_summary("s1", history, metadata=None)

    assert summary["title"] == "Review this screenshot [image]"
    assert summary["last_user_message"] == "Review this screenshot [image]"
    assert summary["last_assistant_preview"] == "Looks good"


def test_local_runtime_async_create_and_rename_session():
    runtime = LocalAgentRuntime(chatbot=_AsyncOnlyChatbot(), store=InMemorySessionStore())

    created = asyncio.run(runtime.create_session_async(title="Async plan", session_id="s1"))
    renamed = asyncio.run(runtime.rename_session_async("s1", "Async renamed"))

    assert created["session_id"] == "s1"
    assert created["title"] == "Async plan"
    assert renamed["title"] == "Async renamed"


def test_local_runtime_workspace_helpers_list_and_read_files(tmp_path: Path):
    runtime = LocalAgentRuntime(
        chatbot=_DummyChatbot(),
        store=InMemorySessionStore(),
        workspace_root_dir=tmp_path / "workspaces",
    )
    asyncio.run(runtime.create_session_async(title="Workspace", session_id="s1"))
    workspace = runtime.workspace_manager.ensure_workspace("s1")  # type: ignore[union-attr]
    (workspace / "doc").mkdir()
    (workspace / "doc" / "design.md").write_text("# Design\n\nHello\n", encoding="utf-8")
    (workspace / "README.md").write_text("root\n", encoding="utf-8")

    tree = asyncio.run(runtime.list_workspace_tree_async("s1", recursive=True))
    file_payload = asyncio.run(
        runtime.read_workspace_file_async("s1", path="doc/design.md"),
    )

    assert tree["session_id"] == "s1"
    assert tree["path"] == "."
    paths = {entry["path"] for entry in tree["entries"]}
    assert "README.md" in paths
    assert "doc" in paths
    assert "doc/design.md" in paths
    for entry in tree["entries"]:
        assert isinstance(entry["updated_at"], str)
        assert entry["updated_at"].endswith("Z")
    assert file_payload == {
        "session_id": "s1",
        "path": "doc/design.md",
        "content": "# Design\n\nHello\n",
        "encoding": "utf-8",
        "truncated": False,
        "line_count": 3,
    }


def test_local_runtime_workspace_helpers_reject_outside_paths(tmp_path: Path):
    runtime = LocalAgentRuntime(
        chatbot=_DummyChatbot(),
        store=InMemorySessionStore(),
        workspace_root_dir=tmp_path / "workspaces",
    )
    asyncio.run(runtime.create_session_async(title="Workspace", session_id="s1"))

    try:
        asyncio.run(runtime.read_workspace_file_async("s1", path="../secret.txt"))
    except ValueError as exc:
        assert "outside the session workspace" in str(exc)
    else:
        raise AssertionError("Expected ValueError for path traversal")


def test_local_runtime_emits_workspace_changed_for_write_file(tmp_path: Path):
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=3)
    base_workspace = tmp_path / "base"
    base_workspace.mkdir()
    chatbot = SimplifiedChatbot(
        config=config,
        provider=_WriteWorkspaceProvider(),
        system_prompt="System prompt",
        tools=build_default_tool_registry(workspace=base_workspace),
        tool_factory=lambda workspace: build_default_tool_registry(workspace=workspace),
        default_workspace=base_workspace,
    )
    runtime = LocalAgentRuntime(
        chatbot=chatbot,
        store=InMemorySessionStore(),
        workspace_root_dir=tmp_path / "workspaces",
    )
    events: list[tuple[str, dict[str, object]]] = []

    result = runtime.handle_message_with_events(
        "s1",
        "Write the design doc",
        on_event=lambda event, data: events.append((event, data)),
    )

    assert result.content == "Wrote the file."
    assert (
        "workspace_changed",
        {"session_id": "s1", "paths": ["doc/design.md"]},
    ) in events


def test_local_runtime_emits_workspace_changed_invalidation_for_exec(tmp_path: Path):
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=3)
    base_workspace = tmp_path / "base"
    base_workspace.mkdir()
    chatbot = SimplifiedChatbot(
        config=config,
        provider=_ExecWorkspaceProvider(),
        system_prompt="System prompt",
        tools=build_default_tool_registry(workspace=base_workspace),
        tool_factory=lambda workspace: build_default_tool_registry(workspace=workspace),
        default_workspace=base_workspace,
    )
    runtime = LocalAgentRuntime(
        chatbot=chatbot,
        store=InMemorySessionStore(),
        workspace_root_dir=tmp_path / "workspaces",
    )
    events: list[tuple[str, dict[str, object]]] = []

    result = runtime.handle_message_with_events(
        "s1",
        "Run a command",
        on_event=lambda event, data: events.append((event, data)),
    )

    assert result.content == "Ran command."
    assert (
        "workspace_changed",
        {"session_id": "s1", "paths": []},
    ) in events


def test_local_runtime_session_workspaces_are_isolated(tmp_path: Path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = _ReadWorkspaceProvider()
    base_workspace = tmp_path / "base"
    base_workspace.mkdir()
    chatbot = SimplifiedChatbot(
        config=config,
        provider=provider,
        system_prompt="System prompt",
        tools=build_default_tool_registry(workspace=base_workspace),
        tool_factory=lambda workspace: build_default_tool_registry(workspace=workspace),
        default_workspace=base_workspace,
    )
    runtime = LocalAgentRuntime(
        chatbot=chatbot,
        store=InMemorySessionStore(),
        workspace_root_dir=tmp_path / "workspaces",
    )

    manager = SessionWorkspaceManager(tmp_path / "workspaces")
    manager.ensure_workspace("s1").joinpath("notes.txt").write_text("session one\n", encoding="utf-8")
    manager.ensure_workspace("s2").joinpath("notes.txt").write_text("session two\n", encoding="utf-8")

    r1 = runtime.handle_message("s1", "read notes")
    r2 = runtime.handle_message("s2", "read notes")

    assert "1| session one" in r1.content
    assert "1| session two" in r2.content
    assert "session two" not in r1.content
    assert "session one" not in r2.content


def test_chatbot_for_workspace_rebuilds_system_prompt(tmp_path: Path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = _ReadWorkspaceProvider()
    base_workspace = tmp_path / "base"
    session_workspace = tmp_path / "workspaces" / "s1"
    base_workspace.mkdir()
    session_workspace.mkdir(parents=True)

    chatbot = SimplifiedChatbot(
        config=config,
        provider=provider,
        system_prompt=f"Workspace: {base_workspace.resolve()}",
        system_prompt_factory=lambda workspace: f"Workspace: {workspace.resolve()}",
        tools=build_default_tool_registry(workspace=base_workspace),
        tool_factory=lambda workspace: build_default_tool_registry(workspace=workspace),
        default_workspace=base_workspace,
    )

    session_chatbot = chatbot.for_workspace(session_workspace)

    assert str(base_workspace.resolve()) in chatbot.system_prompt
    assert str(session_workspace.resolve()) in session_chatbot.system_prompt


def test_local_runtime_from_config_uses_workspace_root_dir_from_config(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "apiKey": "test-key",
                "workspaceRootDir": "agent-workspaces",
            },
        ),
        encoding="utf-8",
    )

    runtime = LocalAgentRuntime.from_config(config_path)

    assert runtime.workspace_manager is not None
    assert runtime.workspace_manager.root_dir == (tmp_path / "agent-workspaces").resolve()


def test_local_runtime_from_config_explicit_workspace_root_overrides_config(tmp_path: Path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "apiKey": "test-key",
                "workspaceRootDir": "agent-workspaces",
            },
        ),
        encoding="utf-8",
    )
    override_root = tmp_path / "custom-workspaces"

    runtime = LocalAgentRuntime.from_config(
        config_path,
        workspace_root_dir=override_root,
    )

    assert runtime.workspace_manager is not None
    assert runtime.workspace_manager.root_dir == override_root.resolve()
