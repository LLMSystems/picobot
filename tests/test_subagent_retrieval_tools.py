from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplified_chatbot.agent.subagent import SubagentManager, SubagentSpec
from simplified_chatbot.tools.subagents import (
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
    assert pending["status"]["phase"] == "running"

    finished = await tool.execute(task_id=task_id, timeout_seconds=1.0)

    assert finished["completed"] is True
    assert finished["result"]["task_id"] == task_id
    assert finished["result"]["ok"] is True
