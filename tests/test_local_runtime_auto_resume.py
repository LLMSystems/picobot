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
