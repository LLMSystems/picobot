"""Subagent retrieval tools for simplified_chatbot."""

from __future__ import annotations

from typing import Any

from simplified_chatbot.agent.subagent import (
    SubagentManager,
    SubagentResult,
    SubagentStatus,
)
from simplified_chatbot.tools.base import Tool, tool_parameters

_PHASES = ["initializing", "running", "done", "error", "cancelled"]


def _serialize_status(
    status: SubagentStatus,
    *,
    tail_tool_events: int | None = None,
) -> dict[str, Any]:
    tool_events = list(status.tool_events)
    if tail_tool_events is not None and tail_tool_events >= 0:
        tool_events = tool_events[-tail_tool_events:] if tail_tool_events else []
    return {
        "task_id": status.task_id,
        "label": status.label,
        "task": status.task,
        "phase": status.phase,
        "iteration": status.iteration,
        "started_at": status.started_at,
        "stop_reason": status.stop_reason,
        "workspace": str(status.workspace) if status.workspace is not None else None,
        "usage": dict(status.usage),
        "error": status.error,
        "tool_events": tool_events,
    }


def _serialize_result(result: SubagentResult) -> dict[str, Any]:
    return {
        "task_id": result.task_id,
        "ok": result.ok,
        "content": result.content,
        "stop_reason": result.stop_reason,
        "workspace": str(result.workspace) if result.workspace is not None else None,
        "usage": dict(result.usage),
        "tool_events": list(result.tool_events),
        "error": result.error,
    }


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "phase": {
                "type": "string",
                "enum": _PHASES,
                "description": "Optional phase filter.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum number of tasks to return.",
            },
            "include_completed": {
                "type": "boolean",
                "description": "Whether to include completed, failed, or cancelled subagents.",
                "default": True,
            },
        },
    },
)
class ListSubagentsTool(Tool):
    """List known subagents so the main agent can recover task ids and phases."""

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "list_subagents"

    @property
    def description(self) -> str:
        return (
            "List known subagents and their phases. "
            "Use this to recover task ids or inspect background work at a glance."
        )

    async def execute(
        self,
        phase: str | None = None,
        limit: int = 20,
        include_completed: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        items = self._manager.list_statuses(
            phase=phase,
            include_completed=include_completed,
            limit=limit,
        )
        return {
            "items": [_serialize_status(item, tail_tool_events=0) for item in items],
            "count": len(items),
        }


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The subagent task id to inspect.",
                "minLength": 1,
            },
            "include_result": {
                "type": "boolean",
                "description": "Include the final result when it is already available.",
                "default": False,
            },
            "tail_tool_events": {
                "type": "integer",
                "minimum": 0,
                "maximum": 20,
                "description": "How many recent tool events to include.",
                "default": 5,
            },
        },
        "required": ["task_id"],
    },
)
class SubagentStatusTool(Tool):
    """Inspect the current status of a specific subagent."""

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "subagent_status"

    @property
    def description(self) -> str:
        return (
            "Inspect one subagent's current status, recent tool activity, and optional final result."
        )

    async def execute(
        self,
        task_id: str,
        include_result: bool = False,
        tail_tool_events: int = 5,
        **kwargs: Any,
    ) -> dict[str, Any]:
        status = self._manager.get_status(task_id)
        if status is None:
            return {"error": f"Unknown subagent task_id: {task_id}"}
        payload = _serialize_status(status, tail_tool_events=tail_tool_events)
        if include_result:
            result = self._manager.get_result(task_id)
            payload["result"] = _serialize_result(result) if result is not None else None
        return payload


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The subagent task id to wait for.",
                "minLength": 1,
            },
            "timeout_seconds": {
                "type": "number",
                "minimum": 0,
                "maximum": 300,
                "description": "How long to wait before returning the current status.",
                "default": 30,
            },
        },
        "required": ["task_id"],
    },
)
class SubagentWaitTool(Tool):
    """Wait for one subagent to finish and return its final result or current status."""

    def __init__(self, manager: SubagentManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "subagent_wait"

    @property
    def description(self) -> str:
        return (
            "Wait for a subagent to finish. "
            "Returns the final result when complete, or the current status if the wait times out."
        )

    async def execute(
        self,
        task_id: str,
        timeout_seconds: float = 30.0,
        **kwargs: Any,
    ) -> dict[str, Any]:
        status = self._manager.get_status(task_id)
        if status is None:
            return {"error": f"Unknown subagent task_id: {task_id}"}
        result = await self._manager.wait_for(
            task_id,
            timeout_seconds=timeout_seconds,
        )
        if result is None:
            status = self._manager.get_status(task_id)
            assert status is not None
            return {
                "completed": False,
                "status": _serialize_status(status, tail_tool_events=5),
            }
        return {
            "completed": True,
            "result": _serialize_result(result),
        }
