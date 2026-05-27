from __future__ import annotations

import asyncio

import pytest

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import InMemorySessionStore


class _DummyChatbot:
    pass


@pytest.mark.asyncio
async def test_internal_message_queue_preserves_order():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())

    runtime._enqueue_internal_message("session-1", {"role": "system", "content": "first"})
    runtime._enqueue_internal_message("session-1", {"role": "system", "content": "second"})

    peeked = runtime._peek_pending_internal_messages("session-1")
    popped = runtime._pop_pending_internal_messages("session-1")

    assert [item["content"] for item in peeked] == ["first", "second"]
    assert [item["content"] for item in popped] == ["first", "second"]
    assert runtime._peek_pending_internal_messages("session-1") == []


@pytest.mark.asyncio
async def test_session_lock_serializes_same_session_work():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())
    events: list[str] = []

    async def run_labeled(label: str) -> None:
        async def runner() -> None:
            events.append(f"start:{label}")
            await asyncio.sleep(0.01)
            events.append(f"end:{label}")

        await runtime._run_with_session_lock("session-1", runner)

    await asyncio.gather(
        run_labeled("a"),
        run_labeled("b"),
    )

    assert events in (
        ["start:a", "end:a", "start:b", "end:b"],
        ["start:b", "end:b", "start:a", "end:a"],
    )


@pytest.mark.asyncio
async def test_background_task_scheduler_dedupes_requests_and_cleans_up():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())
    started = asyncio.Event()
    release = asyncio.Event()
    call_count = 0

    async def background_job() -> None:
        nonlocal call_count
        call_count += 1
        started.set()
        await release.wait()

    scheduled = runtime._schedule_background_session_task("session-1", background_job)
    assert scheduled is True

    await started.wait()

    duplicate = runtime._schedule_background_session_task("session-1", background_job)
    assert duplicate is False
    assert "session-1" in runtime._resume_requested
    assert "session-1" in runtime._background_tasks

    release.set()
    await runtime._background_tasks["session-1"]

    assert call_count == 1
    assert "session-1" not in runtime._resume_requested
    assert "session-1" not in runtime._background_tasks

    rescheduled = runtime._schedule_background_session_task("session-1", background_job)
    assert rescheduled is True
    task = runtime._background_tasks["session-1"]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runtime_persistence_keeps_internal_message_metadata():
    runtime = LocalAgentRuntime(chatbot=_DummyChatbot(), store=InMemorySessionStore())

    history = [
        {
            "role": "system",
            "content": "Internal subagent result",
            "metadata": {
                "internal": True,
                "source": "subagent",
                "task_id": "sub_1234",
            },
        }
    ]

    await runtime._save_history_async("session-1", history)
    loaded = await runtime._load_history_async("session-1")

    assert loaded[0]["role"] == "system"
    assert loaded[0]["content"] == "Internal subagent result"
    assert loaded[0]["metadata"]["internal"] is True
    assert loaded[0]["metadata"]["task_id"] == "sub_1234"
    assert isinstance(loaded[0]["id"], str)
    assert loaded[0]["created_at"].endswith("Z")
