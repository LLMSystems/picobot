"""Subagent spawn tool for simplified_chatbot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from simplified_chatbot.agent.subagent import SubagentManager, SubagentSpec
from simplified_chatbot.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task for the subagent to complete.",
                "minLength": 1,
            },
            "label": {
                "type": "string",
                "description": "Optional short label for display and tracking.",
            },
            "temperature": {
                "type": "number",
                "description": (
                    "Optional sampling temperature for the subagent "
                    "(0.0 = deterministic, higher = more creative)."
                ),
                "minimum": 0.0,
                "maximum": 2.0,
            },
        },
        "required": ["task"],
    },
)
class SpawnTool(Tool):
    """Spawn a background subagent to work on an independent task."""

    def __init__(
        self,
        manager: SubagentManager,
        *,
        workspace: Path | None = None,
    ) -> None:
        self._manager = manager
        self._workspace = workspace.resolve() if workspace is not None else None

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a background subagent for an independent task. "
            "Use this for longer or separable work that does not need to block the current turn. "
            "The subagent result is meant for the main agent, not directly for the end user."
        )

    async def execute(
        self,
        task: str,
        label: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> str:
        task_id = await self._manager.spawn(
            SubagentSpec(
                task=task,
                label=label,
                temperature=temperature,
            ),
            parent_workspace=self._workspace,
        )
        status = self._manager.get_status(task_id)
        display_label = status.label if status is not None else (label or task.strip())
        return f"Subagent [{display_label}] started (id: {task_id})"
