from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplified_chatbot.agent.subagent import SubagentManager, SubagentSpec
from simplified_chatbot.runtime.session_store import AioSQLiteSubagentStore
from simplified_chatbot.tools.subagents import (
    CancelSubagentTool,
    ListSubagentsTool,
    SubagentStatusTool,
    SubagentWaitTool,
)


class _FakeChatbot:
    def __init__(
        self,
        *,
        result: object | None = None,
        delay: float = 0.0,
        event_script: list[tuple[str, dict]] | None = None,
    ) -> None:
        self._result = result or SimpleNamespace(
            content="done",
            stop_reason="completed",
            usage={"prompt_tokens": 3},
        )
        self._delay = delay
        self._event_script = event_script or []

    async def run_async(self, message: str, **kwargs):
        on_event = kwargs.get("on_event")
        for event, data in self._event_script:
            if on_event is not None:
                on_event(event, data)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._result


@pytest.mark.asyncio
async def test_list_subagents_tool_reports_running_and_completed_tasks(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.05),
        max_concurrent_subagents=2,
    )
    running_id = await manager.spawn(
        SubagentSpec(task="running task"),
        parent_workspace=tmp_path,
    )
    completed_id = await manager.spawn(
        SubagentSpec(task="completed task"),
        parent_workspace=tmp_path,
    )
    await manager.wait(completed_id)

    tool = ListSubagentsTool(manager)
    all_items = await tool.execute(include_completed=True, limit=10)
    active_only = await tool.execute(include_completed=False, limit=10)

    assert any(item["task_id"] == running_id for item in all_items["items"])
    assert any(item["task_id"] == completed_id for item in all_items["items"])
    assert all(item["phase"] == "running" for item in active_only["items"])
    assert all(item["tool_events"] == [] for item in all_items["items"])

    await manager.wait(running_id)


@pytest.mark.asyncio
async def test_subagent_status_tool_can_include_result_and_trim_events(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(
            event_script=[
                ("tool_call_started", {"id": "tc1", "name": "glob", "arguments": {"path": "."}}),
                ("tool_call_finished", {"id": "tc1", "name": "glob", "ok": True, "result": ["a.py"]}),
                ("tool_call_started", {"id": "tc2", "name": "read_file", "arguments": {"path": "a.py"}}),
                ("tool_call_finished", {"id": "tc2", "name": "read_file", "ok": True, "result": "hello"}),
            ]
        ),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="inspect file"),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)

    tool = SubagentStatusTool(manager)
    payload = await tool.execute(
        task_id=task_id,
        include_result=True,
        tail_tool_events=1,
    )

    assert payload["task_id"] == task_id
    assert payload["phase"] == "done"
    assert len(payload["tool_events"]) == 1
    assert payload["tool_events"][0]["name"] == "read_file"
    assert payload["result"]["ok"] is True
    assert payload["result"]["content"] == "done"


@pytest.mark.asyncio
async def test_subagent_wait_tool_returns_status_on_timeout_and_result_when_done(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.05),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="slow task"),
        parent_workspace=tmp_path,
    )

    tool = SubagentWaitTool(manager)
    pending = await tool.execute(task_id=task_id, timeout_seconds=0.0)

    assert pending["completed"] is False
    assert pending["status"]["task_id"] == task_id
    assert pending["status"]["phase"] in {"initializing", "running"}

    finished = await tool.execute(task_id=task_id, timeout_seconds=1.0)

    assert finished["completed"] is True
    assert finished["result"]["task_id"] == task_id
    assert finished["result"]["ok"] is True


@pytest.mark.asyncio
async def test_subagent_wait_default_returns_snapshot_without_blocking(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.2),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="slow"),
        parent_workspace=tmp_path,
    )

    tool = SubagentWaitTool(manager)
    snapshot = await tool.execute(task_id=task_id)

    assert snapshot["completed"] is False
    assert snapshot["status"]["phase"] in {"initializing", "running"}

    await manager.wait(task_id)


@pytest.mark.asyncio
async def test_subagent_wait_timeout_zero_returns_result_when_done(tmp_path: Path):
    """Regression: asyncio.wait_for(coro, 0) drops already-done coroutines
    under Python 3.12; the tool must bypass wait_for in snapshot mode so
    completed subagents still surface their result."""
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="fast"),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)

    tool = SubagentWaitTool(manager)
    payload = await tool.execute(task_id=task_id, timeout_seconds=0)

    assert payload["completed"] is True
    assert payload["result"]["task_id"] == task_id
    assert payload["result"]["ok"] is True


@pytest.mark.asyncio
async def test_subagent_wait_include_result_false_omits_result(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="fast"),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)

    tool = SubagentWaitTool(manager)
    payload = await tool.execute(task_id=task_id, include_result=False)

    assert payload == {"completed": True}


@pytest.mark.asyncio
async def test_subagent_wait_tail_tool_events_limits_status_events(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(
            delay=0.2,
            event_script=[
                ("tool_call_started", {"id": "tc1", "name": "glob", "arguments": {}}),
                ("tool_call_finished", {"id": "tc1", "name": "glob", "ok": True, "result": []}),
                ("tool_call_started", {"id": "tc2", "name": "read_file", "arguments": {}}),
                ("tool_call_finished", {"id": "tc2", "name": "read_file", "ok": True, "result": ""}),
            ],
        ),
    )
    task_id = await manager.spawn(
        SubagentSpec(task="emit events"),
        parent_workspace=tmp_path,
    )
    # Give the fake chatbot a beat to flush events but stay running.
    await asyncio.sleep(0.05)

    tool = SubagentWaitTool(manager)
    payload = await tool.execute(task_id=task_id, tail_tool_events=1)

    assert payload["completed"] is False
    assert len(payload["status"]["tool_events"]) == 1

    await manager.wait(task_id)


@pytest.mark.asyncio
async def test_retrieval_tools_fallback_to_persisted_store(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents.db")
    await store.upsert_run(
        {
            "task_id": "sub_persisted_done",
            "parent_session_id": "session_a",
            "label": "persisted task",
            "task": "Persisted task",
            "workspace": str(tmp_path / "session_a" / ".subagents" / "sub_persisted_done"),
            "phase": "done",
            "started_at": "2026-05-27T12:00:00Z",
            "finished_at": "2026-05-27T12:00:05Z",
            "stop_reason": "stop",
            "ok": True,
            "error": None,
            "usage": {"prompt_tokens": 8},
            "tool_events": [{"id": "tc1", "name": "write_file", "status": "ok"}],
            "final_content": "Finished persisted work",
        },
    )
    await store.upsert_run(
        {
            "task_id": "sub_other_session",
            "parent_session_id": "session_b",
            "label": "other session task",
            "task": "Other session task",
            "workspace": None,
            "phase": "done",
            "started_at": "2026-05-27T12:00:10Z",
            "finished_at": "2026-05-27T12:00:12Z",
            "stop_reason": "completed",
            "ok": True,
            "error": None,
            "usage": {},
            "tool_events": [],
            "final_content": "other",
        },
    )

    manager = SubagentManager(lambda _workspace, _model: _FakeChatbot())
    list_tool = ListSubagentsTool(manager, session_id="session_a", store=store)
    status_tool = SubagentStatusTool(manager, session_id="session_a", store=store)
    wait_tool = SubagentWaitTool(manager, session_id="session_a", store=store)

    listing = await list_tool.execute(include_completed=True, limit=10)
    status_payload = await status_tool.execute(
        task_id="sub_persisted_done",
        include_result=True,
        tail_tool_events=1,
    )
    waited = await wait_tool.execute(
        task_id="sub_persisted_done",
        timeout_seconds=0.0,
    )

    assert [item["task_id"] for item in listing["items"]] == ["sub_persisted_done"]
    assert status_payload["phase"] == "done"
    assert status_payload["started_at"] == "2026-05-27T12:00:00Z"
    assert status_payload["tool_events"][0]["name"] == "write_file"
    assert status_payload["result"]["content"] == "Finished persisted work"
    assert waited["completed"] is True
    assert waited["result"]["task_id"] == "sub_persisted_done"
    assert waited["result"]["ok"] is True


@pytest.mark.asyncio
async def test_status_tool_rejects_persisted_task_from_other_session(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents.db")
    await store.upsert_run(
        {
            "task_id": "sub_hidden",
            "parent_session_id": "session_b",
            "label": "hidden task",
            "task": "Hidden task",
            "workspace": None,
            "phase": "done",
            "started_at": "2026-05-27T12:00:00Z",
            "finished_at": "2026-05-27T12:00:01Z",
            "stop_reason": "completed",
            "ok": True,
            "error": None,
            "usage": {},
            "tool_events": [],
            "final_content": "hidden",
        },
    )

    tool = SubagentStatusTool(
        SubagentManager(lambda _workspace, _model: _FakeChatbot()),
        session_id="session_a",
        store=store,
    )
    payload = await tool.execute(task_id="sub_hidden")

    assert payload["error"] == "Unknown subagent task_id: sub_hidden"


@pytest.mark.asyncio
async def test_cancel_subagent_tool_cancels_running_task(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.2),
    )
    task_id = await manager.spawn(
        SubagentSpec(
            task="cancel me",
            parent_session_id="session_a",
        ),
        parent_workspace=tmp_path,
    )
    tool = CancelSubagentTool(
        manager,
        session_id="session_a",
    )

    payload = await tool.execute(task_id=task_id)
    result = await manager.wait(task_id)

    assert payload == {
        "found": True,
        "cancelled": True,
        "task_id": task_id,
        "phase": "cancelled",
    }
    assert result.stop_reason == "cancelled"
    assert result.ok is False


@pytest.mark.asyncio
async def test_cancel_subagent_tool_returns_terminal_phase_for_completed_task(tmp_path: Path):
    manager = SubagentManager(lambda _workspace, _model: _FakeChatbot())
    task_id = await manager.spawn(
        SubagentSpec(
            task="finish first",
            parent_session_id="session_a",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)
    tool = CancelSubagentTool(
        manager,
        session_id="session_a",
    )

    payload = await tool.execute(task_id=task_id)

    assert payload == {
        "found": True,
        "cancelled": False,
        "task_id": task_id,
        "phase": "done",
    }


@pytest.mark.asyncio
async def test_cancel_subagent_tool_rejects_task_from_other_session(tmp_path: Path):
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.2),
    )
    task_id = await manager.spawn(
        SubagentSpec(
            task="hidden task",
            parent_session_id="session_b",
        ),
        parent_workspace=tmp_path,
    )
    tool = CancelSubagentTool(
        manager,
        session_id="session_a",
    )

    payload = await tool.execute(task_id=task_id)

    assert payload == {
        "found": False,
        "cancelled": False,
        "task_id": task_id,
    }
    await manager.cancel(task_id)


@pytest.mark.asyncio
async def test_cancel_subagent_tool_falls_back_to_persisted_terminal_task(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents.db")
    await store.upsert_run(
        {
            "task_id": "sub_persisted_cancelled",
            "parent_session_id": "session_a",
            "label": "persisted task",
            "task": "Persisted task",
            "workspace": None,
            "phase": "cancelled",
            "started_at": "2026-05-27T12:00:00Z",
            "finished_at": "2026-05-27T12:00:01Z",
            "stop_reason": "cancelled",
            "ok": False,
            "error": None,
            "usage": {},
            "tool_events": [],
            "final_content": "Cancelled",
        },
    )

    tool = CancelSubagentTool(
        SubagentManager(lambda _workspace, _model: _FakeChatbot()),
        session_id="session_a",
        store=store,
    )

    payload = await tool.execute(task_id="sub_persisted_cancelled")

    assert payload == {
        "found": True,
        "cancelled": False,
        "task_id": "sub_persisted_cancelled",
        "phase": "cancelled",
    }


@pytest.mark.asyncio
async def test_cancel_subagent_tool_rejects_persisted_task_from_other_session(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents.db")
    await store.upsert_run(
        {
            "task_id": "sub_hidden_persisted",
            "parent_session_id": "session_b",
            "label": "hidden persisted task",
            "task": "Hidden persisted task",
            "workspace": None,
            "phase": "done",
            "started_at": "2026-05-27T12:00:00Z",
            "finished_at": "2026-05-27T12:00:01Z",
            "stop_reason": "completed",
            "ok": True,
            "error": None,
            "usage": {},
            "tool_events": [],
            "final_content": "hidden",
        },
    )

    tool = CancelSubagentTool(
        SubagentManager(lambda _workspace, _model: _FakeChatbot()),
        session_id="session_a",
        store=store,
    )

    payload = await tool.execute(task_id="sub_hidden_persisted")

    assert payload == {
        "found": False,
        "cancelled": False,
        "task_id": "sub_hidden_persisted",
    }
