from __future__ import annotations

from pathlib import Path

import pytest

from simplified_chatbot.agent.subagent import SubagentManager, SubagentSpec
from simplified_chatbot.tools.spawn import SpawnTool


class _StubManager:
    def __init__(self) -> None:
        self.seen_spec: SubagentSpec | None = None
        self.seen_parent_workspace: Path | None = None

    async def spawn(
        self,
        spec: SubagentSpec,
        *,
        parent_workspace: Path | None = None,
    ) -> str:
        self.seen_spec = spec
        self.seen_parent_workspace = parent_workspace
        return "sub_deadbeef"

    def get_status(self, task_id: str):
        assert task_id == "sub_deadbeef"
        return type("Status", (), {"label": "collect refs"})()


@pytest.mark.asyncio
async def test_spawn_tool_delegates_to_subagent_manager():
    manager = _StubManager()
    workspace = Path.cwd() / "main-workspace"
    tool = SpawnTool(
        manager,
        workspace=workspace,
        parent_session_id="session_123",
    )  # type: ignore[arg-type]

    result = await tool.execute(
        task="collect references",
        label="collect refs",
        temperature=0.3,
    )

    assert manager.seen_spec is not None
    assert manager.seen_spec.task == "collect references"
    assert manager.seen_spec.label == "collect refs"
    assert manager.seen_spec.temperature == 0.3
    assert manager.seen_spec.parent_session_id == "session_123"
    assert manager.seen_parent_workspace == workspace.resolve()
    assert "started" in result
    assert "sub_deadbeef" in result


@pytest.mark.asyncio
async def test_spawn_tool_propagates_manager_error():
    class _FailingManager:
        async def spawn(
            self,
            spec: SubagentSpec,
            *,
            parent_workspace: Path | None = None,
        ) -> str:
            raise RuntimeError("limit reached")

        def get_status(self, task_id: str):
            return None

    tool = SpawnTool(_FailingManager())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="limit reached"):
        await tool.execute(task="collect references")
