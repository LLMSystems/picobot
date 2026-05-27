from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from simplified_chatbot.agent.subagent import SubagentManager, SubagentSpec
from simplified_chatbot.agent.types import Message, MessageContent
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore, InMemorySessionStore


class _DummyResult:
    def __init__(self, *, messages: list[Message], content: str) -> None:
        self.messages = messages
        self.content = content
        self.model = "dummy"
        self.provider = "dummy"
        self.usage = {}
        self.tools_used = []
        self.stop_reason = "completed"


class _FakeSubagentChatbot:
    def __init__(self, *, content: str = "subagent done", delay: float = 0.0) -> None:
        self._content = content
        self._delay = delay

    async def run_async(self, message: str, **kwargs):
        if self._delay:
            await asyncio.sleep(self._delay)
        return SimpleNamespace(
            content=self._content,
            stop_reason="completed",
            usage={"prompt_tokens": 2},
        )


class _FakeStreamingSubagentChatbot(_FakeSubagentChatbot):
    def __init__(
        self,
        *,
        content: str = "subagent done",
        delay: float = 0.0,
        deltas: list[str] | None = None,
        event_script: list[tuple[str, dict[str, object]]] | None = None,
    ) -> None:
        super().__init__(content=content, delay=delay)
        self._deltas = deltas or []
        self._event_script = event_script or []

    async def run_stream_async(self, message: str, **kwargs):
        on_delta = kwargs.get("on_delta")
        on_event = kwargs.get("on_event")
        for delta in self._deltas:
            if on_delta is not None:
                on_delta(delta)
        for event, data in self._event_script:
            if on_event is not None:
                on_event(event, data)
        if self._delay:
            await asyncio.sleep(self._delay)
        return SimpleNamespace(
            content=self._content,
            stop_reason="completed",
            usage={"prompt_tokens": 3},
        )


class _AutoResumeChatbot:
    def __init__(self, manager: SubagentManager) -> None:
        self.subagent_manager = manager
        self.continue_calls: list[list[Message]] = []
        self.run_calls: list[tuple[MessageContent, list[Message]]] = []
        self.config = ChatbotConfig(model="gpt-4.1-mini")

    async def continue_async(
        self,
        history: list[Message],
        *,
        model_override: str | None = None,
        on_event=None,
    ):
        self.continue_calls.append([dict(item) for item in history])
        messages = [
            *history,
            {"role": "assistant", "content": "auto-resumed"},
        ]
        return _DummyResult(messages=messages, content="auto-resumed")

    async def run_async(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        model_override: str | None = None,
        on_event=None,
    ):
        normalized_history = [dict(item) for item in (history or [])]
        self.run_calls.append((message, normalized_history))
        messages = [
            *normalized_history,
            {"role": "user", "content": message},
            {"role": "assistant", "content": "user-run"},
        ]
        return _DummyResult(messages=messages, content="user-run")


@pytest.mark.asyncio
async def test_subagent_completion_auto_resumes_same_session():
    manager = SubagentManager(lambda _workspace, _model: _FakeSubagentChatbot(content="collected refs"))
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())

    await runtime._save_history_async(
        "session-1",
        [{"role": "assistant", "content": "working"}],
    )

    task_id = await manager.spawn(
        SubagentSpec(
            task="collect references",
            parent_session_id="session-1",
        ),
    )
    await manager.wait(task_id)
    background_task = runtime._background_tasks.get("session-1")
    if background_task is not None:
        await background_task
    else:
        await asyncio.sleep(0)

    assert len(bot.continue_calls) == 1
    history = bot.continue_calls[0]
    assert history[0]["content"] == "working"
    assert history[1]["role"] == "system"
    assert history[1]["metadata"]["internal"] is True
    assert history[1]["metadata"]["source"] == "subagent"
    assert history[1]["metadata"]["task_id"] == task_id
    assert "collect references" in history[1]["content"]
    assert "collected refs" in history[1]["content"]

    stored = await runtime._load_history_async("session-1")
    assert stored[-1]["role"] == "assistant"
    assert stored[-1]["content"] == "auto-resumed"


@pytest.mark.asyncio
async def test_auto_resume_waits_for_session_lock_release():
    manager = SubagentManager(lambda _workspace, _model: _FakeSubagentChatbot())
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())
    lock = runtime._get_session_lock("session-2")
    await lock.acquire()

    task_id = await manager.spawn(
        SubagentSpec(
            task="background work",
            parent_session_id="session-2",
        ),
    )
    await manager.wait(task_id)
    await asyncio.sleep(0.01)

    assert "session-2" in runtime._background_tasks
    assert bot.continue_calls == []

    lock.release()
    await runtime._background_tasks["session-2"]

    assert len(bot.continue_calls) == 1


@pytest.mark.asyncio
async def test_user_run_consumes_pending_internal_messages_before_reply():
    manager = SubagentManager(lambda _workspace, _model: _FakeSubagentChatbot())
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())

    runtime._enqueue_internal_message(
        "session-3",
        {
            "role": "system",
            "content": "Internal subagent result",
            "metadata": {"internal": True, "source": "subagent"},
        },
    )

    result = await runtime.handle_input_async("session-3", "hello")

    assert result.content == "user-run"
    assert bot.run_calls[0][1][0]["role"] == "system"
    assert bot.run_calls[0][1][0]["content"] == "Internal subagent result"
    assert runtime._peek_pending_internal_messages("session-3") == []


@pytest.mark.asyncio
async def test_runtime_observes_live_subagent_events_in_process(tmp_path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeSubagentChatbot(delay=0.01),
    )
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())

    task_id = await manager.spawn(
        SubagentSpec(
            task="live background work",
            parent_session_id="session-live",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)
    await asyncio.sleep(0)

    events = runtime._recent_subagent_events["session-live"]
    event_names = [item["event"] for item in events]
    assert "subagent_spawned" in event_names
    assert "subagent_phase_changed" in event_names
    assert "subagent_completed" in event_names


@pytest.mark.asyncio
async def test_subagent_spawn_and_completion_are_persisted(tmp_path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "runtime.db")
    manager = SubagentManager(
        lambda _workspace, _model: _FakeSubagentChatbot(
            content="created scratch notes",
            delay=0.05,
        ),
    )
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=store)

    task_id = await manager.spawn(
        SubagentSpec(
            task="create scratch notes",
            parent_session_id="session-4",
        ),
        parent_workspace=tmp_path / "workspaces" / "session-4",
    )

    persisted = await runtime.subagent_store.get_run(task_id)
    assert persisted is not None
    assert persisted["task_id"] == task_id
    assert persisted["parent_session_id"] == "session-4"
    assert persisted["phase"] == "initializing"
    assert persisted["ok"] is None
    assert persisted["final_content"] is None
    assert persisted["started_at"].endswith("Z")
    assert persisted["workspace"].endswith(f".subagents/{task_id}".replace("/", "\\"))

    await manager.wait(task_id)
    background_task = runtime._background_tasks.get("session-4")
    if background_task is not None:
        await background_task

    completed = await runtime.subagent_store.get_run(task_id)
    assert completed is not None
    assert completed["phase"] == "done"
    assert completed["ok"] is True
    assert completed["stop_reason"] == "completed"
    assert completed["final_content"] == "created scratch notes"
    assert completed["finished_at"].endswith("Z")
    assert completed["started_at"] == persisted["started_at"]


@pytest.mark.asyncio
async def test_subagent_live_events_are_persisted_to_sqlite(tmp_path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "runtime.db")
    manager = SubagentManager(
        lambda _workspace, _model: _FakeStreamingSubagentChatbot(
            content="streamed result",
            deltas=["hello", " world"],
            event_script=[
                ("tool_call_started", {"id": "tc1", "name": "glob", "arguments": {"path": "."}}),
                ("tool_call_finished", {"id": "tc1", "name": "glob", "ok": True, "result": ["a.py"]}),
                ("iteration_completed", {"iteration": 1, "usage": {"prompt_tokens": 3}}),
            ],
        ),
    )
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=store)

    task_id = await manager.spawn(
        SubagentSpec(
            task="stream and inspect",
            parent_session_id="session-events",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)
    await asyncio.sleep(0)

    persisted = await runtime.subagent_event_store.list_events(
        task_id,
        parent_session_id="session-events",
    )

    assert [item["seq"] for item in persisted] == list(range(1, len(persisted) + 1))
    event_types = [item["event_type"] for item in persisted]
    assert event_types[0] == "subagent_spawned"
    assert "subagent_delta" in event_types
    assert "subagent_tool_call_started" in event_types
    assert "subagent_tool_call_finished" in event_types
    assert "subagent_iteration_completed" in event_types
    assert "subagent_completed" in event_types
    delta_payloads = [
        item["payload"]["data"]["delta"]
        for item in persisted
        if item["event_type"] == "subagent_delta"
    ]
    assert delta_payloads == ["hello", " world"]


@pytest.mark.asyncio
async def test_session_event_subscriber_receives_live_subagent_events(tmp_path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeStreamingSubagentChatbot(
            content="streamed result",
            deltas=["hi"],
            event_script=[
                ("tool_call_started", {"id": "tc1", "name": "glob", "arguments": {"path": "."}}),
                ("tool_call_finished", {"id": "tc1", "name": "glob", "ok": True, "result": ["a.py"]}),
            ],
        ),
    )
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())
    subscriber = runtime.subscribe_session_events("session-sse")

    task_id = await manager.spawn(
        SubagentSpec(
            task="stream live events",
            parent_session_id="session-sse",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)

    seen: list[dict[str, object]] = []
    while True:
        item = await asyncio.wait_for(subscriber.get(), timeout=0.5)
        seen.append(item)
        if item["event"] == "subagent_completed":
            break

    event_names = [item["event"] for item in seen]
    assert seen[0]["session_id"] == "session-sse"
    assert seen[0]["task_id"] == task_id
    assert "subagent_spawned" in event_names
    assert "subagent_delta" in event_names
    assert "subagent_tool_call_started" in event_names
    assert "subagent_tool_call_finished" in event_names
    assert "subagent_completed" in event_names
    assert [item["seq"] for item in seen] == list(range(1, len(seen) + 1))


@pytest.mark.asyncio
async def test_unsubscribed_session_event_queue_stops_receiving_updates(tmp_path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeSubagentChatbot(delay=0.01),
    )
    bot = _AutoResumeChatbot(manager)
    runtime = LocalAgentRuntime(chatbot=bot, store=InMemorySessionStore())
    subscriber = runtime.subscribe_session_events("session-unsub")
    runtime.unsubscribe_session_events("session-unsub", subscriber)

    task_id = await manager.spawn(
        SubagentSpec(
            task="should not be delivered",
            parent_session_id="session-unsub",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)
    await asyncio.sleep(0)

    assert subscriber.empty()
