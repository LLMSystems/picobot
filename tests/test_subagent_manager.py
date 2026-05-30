from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from simplified_chatbot.agent.subagent import (
    SubagentManager,
    SubagentResult,
    SubagentSpec,
)


class _FakeChatbot:
    def __init__(
        self,
        *,
        result: object | None = None,
        delay: float = 0.0,
        error: Exception | None = None,
        event_script: list[tuple[str, dict]] | None = None,
    ) -> None:
        self._result = result or SimpleNamespace(
            content="done",
            stop_reason="completed",
            usage={"prompt_tokens": 1},
        )
        self._delay = delay
        self._error = error
        self._event_script = event_script or []

    async def run_async(self, message: str, **kwargs):
        on_event = kwargs.get("on_event")
        for event, data in self._event_script:
            if on_event is not None:
                on_event(event, data)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


class _FakeStreamingChatbot(_FakeChatbot):
    def __init__(
        self,
        *,
        deltas: list[str] | None = None,
        result: object | None = None,
        delay: float = 0.0,
        event_script: list[tuple[str, dict]] | None = None,
    ) -> None:
        super().__init__(
            result=result,
            delay=delay,
            event_script=event_script,
        )
        self._deltas = deltas or []
        self.used_stream = False

    async def run_stream_async(self, message: str, **kwargs):
        self.used_stream = True
        on_event = kwargs.get("on_event")
        on_delta = kwargs.get("on_delta")
        for delta in self._deltas:
            if on_delta is not None:
                on_delta(delta)
        for event, data in self._event_script:
            if on_event is not None:
                on_event(event, data)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return self._result


@pytest.mark.asyncio
async def test_spawn_returns_task_id_and_result():
    manager = SubagentManager(lambda _workspace, _model: _FakeChatbot())

    task_id = await manager.spawn(SubagentSpec(task="collect notes"))
    result = await manager.wait(task_id)

    assert task_id.startswith("sub_")
    assert isinstance(result, SubagentResult)
    assert result.ok is True
    assert result.content == "done"


@pytest.mark.asyncio
async def test_resolve_model_is_recorded_on_status_before_run():
    seen: list[str | None] = []

    def resolver(spec):
        seen.append(spec.model_override)
        return spec.model_override or "default-fallback"

    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(),
        max_concurrent_subagents=2,
        resolve_model=resolver,
    )

    task_id_a = await manager.spawn(SubagentSpec(task="a", model_override="gpt-5-nano"))
    task_id_b = await manager.spawn(SubagentSpec(task="b"))
    await manager.wait(task_id_a)
    await manager.wait(task_id_b)

    assert seen == ["gpt-5-nano", None]
    assert manager.get_status(task_id_a).model == "gpt-5-nano"
    assert manager.get_status(task_id_b).model == "default-fallback"


@pytest.mark.asyncio
async def test_running_count_tracks_background_tasks():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.05),
        max_concurrent_subagents=2,
    )

    task_a = await manager.spawn(SubagentSpec(task="task a"))
    task_b = await manager.spawn(SubagentSpec(task="task b"))

    assert manager.get_running_count() == 2
    assert {status.task_id for status in manager.list_running()} == {task_a, task_b}

    await manager.wait(task_a)
    await manager.wait(task_b)
    assert manager.get_running_count() == 0


@pytest.mark.asyncio
async def test_concurrency_limit_rejects_extra_spawn():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.05),
        max_concurrent_subagents=1,
    )

    task_id = await manager.spawn(SubagentSpec(task="first"))
    assert task_id
    with pytest.raises(RuntimeError, match="concurrency limit reached"):
        await manager.spawn(SubagentSpec(task="second"))
    await manager.wait(task_id)


@pytest.mark.asyncio
async def test_cancel_marks_task_cancelled():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=1.0),
        max_concurrent_subagents=1,
    )

    task_id = await manager.spawn(SubagentSpec(task="long task"))
    cancelled = await manager.cancel(task_id)
    result = await manager.wait(task_id)

    assert cancelled is True
    assert result.stop_reason == "cancelled"
    assert result.ok is False
    assert manager.get_status(task_id).phase == "cancelled"


@pytest.mark.asyncio
async def test_error_result_is_captured():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(error=RuntimeError("boom")),
    )

    task_id = await manager.spawn(SubagentSpec(task="explode"))
    result = await manager.wait(task_id)

    assert result.ok is False
    assert result.stop_reason == "error"
    assert "boom" in (result.error or "")
    assert manager.get_status(task_id).phase == "error"


@pytest.mark.asyncio
async def test_stop_finish_reason_is_treated_as_success():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(
            result=SimpleNamespace(
                content="done",
                stop_reason="stop",
                usage={"prompt_tokens": 2},
            )
        ),
    )

    task_id = await manager.spawn(SubagentSpec(task="finish normally"))
    result = await manager.wait(task_id)

    assert result.ok is True
    assert result.stop_reason == "stop"
    assert manager.get_status(task_id).phase == "done"


@pytest.mark.asyncio
async def test_tool_events_update_status():
    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(
            event_script=[
                ("tool_call_started", {"id": "tc1", "name": "read_file", "arguments": {"path": "a.txt"}}),
                ("tool_call_finished", {"id": "tc1", "name": "read_file", "ok": True, "result": "hello"}),
                ("iteration_completed", {"iteration": 2, "usage": {"prompt_tokens": 12}}),
            ]
        )
    )

    task_id = await manager.spawn(SubagentSpec(task="inspect file"))
    result = await manager.wait(task_id)
    status = manager.get_status(task_id)

    assert result.tool_events[0]["name"] == "read_file"
    assert result.tool_events[0]["status"] == "ok"
    assert status.iteration == 2
    assert status.usage == {"prompt_tokens": 12}


@pytest.mark.asyncio
async def test_factory_receives_workspace_and_model_override(tmp_path: Path):
    captured: dict[str, object] = {}

    def factory(workspace: Path | None, model_override: str | None):
        captured["workspace"] = workspace
        captured["model_override"] = model_override
        return _FakeChatbot()

    manager = SubagentManager(factory)
    workspace = tmp_path / ".subagents" / "sub_12345678"

    task_id = await manager.spawn(
        SubagentSpec(
            task="collect references",
            workspace=workspace,
            model_override="gpt-5-mini",
            parent_session_id="session_123",
        )
    )
    await manager.wait(task_id)

    assert captured["workspace"] == workspace
    assert captured["model_override"] == "gpt-5-mini"
    assert manager.get_status(task_id).parent_session_id == "session_123"


@pytest.mark.asyncio
async def test_spawn_allocates_workspace_under_parent_workspace(tmp_path: Path):
    captured: dict[str, object] = {}

    def factory(workspace: Path | None, model_override: str | None):
        captured["workspace"] = workspace
        captured["model_override"] = model_override
        return _FakeChatbot()

    manager = SubagentManager(factory)
    parent_workspace = tmp_path / "session-workspace"
    parent_workspace.mkdir()

    task_id = await manager.spawn(
        SubagentSpec(task="collect references"),
        parent_workspace=parent_workspace,
    )
    result = await manager.wait(task_id)
    status = manager.get_status(task_id)
    expected_workspace = parent_workspace / ".subagents" / task_id

    assert status is not None
    assert status.workspace == expected_workspace.resolve()
    assert result.workspace == expected_workspace.resolve()
    assert captured["workspace"] == expected_workspace.resolve()
    assert expected_workspace.is_dir()


@pytest.mark.asyncio
async def test_explicit_relative_workspace_resolves_against_parent_workspace(tmp_path: Path):
    captured: dict[str, object] = {}

    def factory(workspace: Path | None, model_override: str | None):
        captured["workspace"] = workspace
        captured["model_override"] = model_override
        return _FakeChatbot()

    manager = SubagentManager(factory)
    parent_workspace = tmp_path / "session-workspace"
    parent_workspace.mkdir()

    task_id = await manager.spawn(
        SubagentSpec(
            task="write notes",
            workspace=Path("scratch") / "job-a",
        ),
        parent_workspace=parent_workspace,
    )
    result = await manager.wait(task_id)
    expected_workspace = (parent_workspace / "scratch" / "job-a").resolve()

    assert manager.get_status(task_id).workspace == expected_workspace
    assert result.workspace == expected_workspace
    assert captured["workspace"] == expected_workspace
    assert expected_workspace.is_dir()


@pytest.mark.asyncio
async def test_result_callback_receives_completed_result_with_parent_session_id(tmp_path: Path):
    seen: dict[str, object] = {}

    async def result_callback(status, result):
        seen["status"] = status
        seen["result"] = result

    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(),
        result_callback=result_callback,
    )

    task_id = await manager.spawn(
        SubagentSpec(
            task="collect notes",
            parent_session_id="session_alpha",
        ),
        parent_workspace=tmp_path,
    )
    result = await manager.wait(task_id)

    status = seen["status"]
    callback_result = seen["result"]
    assert status.task_id == task_id
    assert status.parent_session_id == "session_alpha"
    assert callback_result.task_id == task_id
    assert callback_result.ok is True
    assert callback_result.content == result.content


@pytest.mark.asyncio
async def test_result_callback_receives_error_result(tmp_path: Path):
    seen: dict[str, object] = {}

    async def result_callback(status, result):
        seen["status"] = status
        seen["result"] = result

    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(error=RuntimeError("boom")),
        result_callback=result_callback,
    )

    task_id = await manager.spawn(
        SubagentSpec(
            task="explode",
            parent_session_id="session_beta",
        ),
        parent_workspace=tmp_path,
    )
    result = await manager.wait(task_id)

    status = seen["status"]
    callback_result = seen["result"]
    assert status.task_id == task_id
    assert status.parent_session_id == "session_beta"
    assert callback_result.task_id == task_id
    assert callback_result.ok is False
    assert callback_result.stop_reason == "error"
    assert "boom" in (result.error or "")


@pytest.mark.asyncio
async def test_spawn_callback_receives_initializing_status(tmp_path: Path):
    seen: dict[str, object] = {}

    async def spawn_callback(status):
        seen["snapshot"] = {
            "task_id": status.task_id,
            "phase": status.phase,
            "parent_session_id": status.parent_session_id,
            "workspace": status.workspace,
            "started_at_utc": status.started_at_utc,
        }

    manager = SubagentManager(
        lambda _workspace, _model: _FakeChatbot(delay=0.01),
        spawn_callback=spawn_callback,
    )

    task_id = await manager.spawn(
        SubagentSpec(
            task="prepare scratch space",
            parent_session_id="session_gamma",
        ),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)

    status = seen["snapshot"]
    assert status["task_id"] == task_id
    assert status["phase"] == "initializing"
    assert status["parent_session_id"] == "session_gamma"
    assert status["workspace"] == (tmp_path / ".subagents" / task_id).resolve()
    assert isinstance(status["started_at_utc"], str)
    assert status["started_at_utc"].endswith("Z")


@pytest.mark.asyncio
async def test_event_callback_receives_streaming_and_terminal_events(tmp_path: Path):
    seen: list[tuple[str, dict[str, object]]] = []
    chatbot = _FakeStreamingChatbot(
        deltas=["hello", " world"],
        event_script=[
            ("tool_call_started", {"id": "tc1", "name": "read_file", "arguments": {"path": "a.txt"}}),
            ("tool_call_finished", {"id": "tc1", "name": "read_file", "ok": True, "result": "content"}),
            ("iteration_completed", {"iteration": 1, "usage": {"prompt_tokens": 5}}),
        ],
    )

    async def event_callback(status, event, payload):
        seen.append((event, dict(payload)))

    manager = SubagentManager(
        lambda _workspace, _model: chatbot,
        event_callback=event_callback,
    )

    task_id = await manager.spawn(
        SubagentSpec(task="stream task"),
        parent_workspace=tmp_path,
    )
    await manager.wait(task_id)
    await asyncio.sleep(0)

    event_names = [name for name, _payload in seen]
    assert chatbot.used_stream is True
    assert event_names[0] == "subagent_spawned"
    assert "subagent_phase_changed" in event_names
    assert ("subagent_delta", {"delta": "hello"}) in seen
    assert ("subagent_delta", {"delta": " world"}) in seen
    assert any(name == "subagent_tool_call_started" for name in event_names)
    assert any(name == "subagent_tool_call_finished" for name in event_names)
    assert any(name == "subagent_iteration_completed" for name in event_names)
    assert any(name == "subagent_completed" for name in event_names)


@pytest.mark.asyncio
async def test_streaming_subagent_falls_back_to_run_async_when_stream_not_supported():
    manager = SubagentManager(lambda _workspace, _model: _FakeChatbot())

    task_id = await manager.spawn(SubagentSpec(task="fallback task"))
    result = await manager.wait(task_id)

    assert result.ok is True
    assert result.content == "done"
