"""Subagent retrieval tools for simplified_chatbot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simplified_chatbot.agent.subagent import (
    SubagentManager,
    SubagentResult,
    SubagentStatus,
)
from simplified_chatbot.tools.base import Tool, tool_parameters

if TYPE_CHECKING:
    from simplified_chatbot.runtime.session_store import AioSQLiteSubagentStore

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


def _serialize_persisted_status(
    payload: dict[str, Any],
    *,
    tail_tool_events: int | None = None,
) -> dict[str, Any]:
    tool_events = list(payload.get("tool_events", []))
    if tail_tool_events is not None and tail_tool_events >= 0:
        tool_events = tool_events[-tail_tool_events:] if tail_tool_events else []
    return {
        "task_id": payload.get("task_id"),
        "label": payload.get("label"),
        "task": payload.get("task"),
        "phase": payload.get("phase"),
        "iteration": 0,
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "stop_reason": payload.get("stop_reason"),
        "workspace": payload.get("workspace"),
        "usage": dict(payload.get("usage", {})),
        "error": payload.get("error"),
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


def _serialize_persisted_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": payload.get("task_id"),
        "ok": payload.get("ok"),
        "content": payload.get("final_content"),
        "stop_reason": payload.get("stop_reason"),
        "workspace": payload.get("workspace"),
        "usage": dict(payload.get("usage", {})),
        "tool_events": list(payload.get("tool_events", [])),
        "error": payload.get("error"),
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

    def __init__(
        self,
        manager: SubagentManager,
        *,
        session_id: str | None = None,
        store: AioSQLiteSubagentStore | None = None,
    ) -> None:
        self._manager = manager
        self._session_id = session_id
        self._store = store

    def bind_store(self, store: AioSQLiteSubagentStore | None) -> None:
        self._store = store

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
        memory_items = self._manager.list_statuses(
            phase=phase,
            include_completed=include_completed,
            limit=limit,
        )
        items = [_serialize_status(item, tail_tool_events=0) for item in memory_items]
        seen_task_ids = {item["task_id"] for item in items}
        if self._store is not None:
            persisted_items = await self._store.list_runs(
                parent_session_id=self._session_id,
                phase=phase,
                limit=limit,
            )
            for payload in persisted_items:
                task_id = payload.get("task_id")
                if task_id in seen_task_ids:
                    continue
                if not include_completed and payload.get("phase") in {"done", "error", "cancelled"}:
                    continue
                items.append(_serialize_persisted_status(payload, tail_tool_events=0))
                seen_task_ids.add(task_id)
        items = items[:limit]
        return {
            "items": items,
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

    def __init__(
        self,
        manager: SubagentManager,
        *,
        session_id: str | None = None,
        store: AioSQLiteSubagentStore | None = None,
    ) -> None:
        self._manager = manager
        self._session_id = session_id
        self._store = store

    def bind_store(self, store: AioSQLiteSubagentStore | None) -> None:
        self._store = store

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
        if status is not None:
            payload = _serialize_status(status, tail_tool_events=tail_tool_events)
            if include_result:
                result = self._manager.get_result(task_id)
                if result is not None:
                    payload["result"] = _serialize_result(result)
                elif self._store is not None:
                    persisted = await self._store.get_run(task_id)
                    if (
                        persisted is not None
                        and (self._session_id is None or persisted.get("parent_session_id") == self._session_id)
                    ):
                        payload["result"] = _serialize_persisted_result(persisted)
                    else:
                        payload["result"] = None
                else:
                    payload["result"] = None
            return payload
        if self._store is None:
            return {"error": f"Unknown subagent task_id: {task_id}"}
        persisted = await self._store.get_run(task_id)
        if persisted is None or (
            self._session_id is not None and persisted.get("parent_session_id") != self._session_id
        ):
            return {"error": f"Unknown subagent task_id: {task_id}"}
        payload = _serialize_persisted_status(persisted, tail_tool_events=tail_tool_events)
        if include_result and persisted.get("phase") in {"done", "error", "cancelled"}:
            payload["result"] = _serialize_persisted_result(persisted)
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

    def __init__(
        self,
        manager: SubagentManager,
        *,
        session_id: str | None = None,
        store: AioSQLiteSubagentStore | None = None,
    ) -> None:
        self._manager = manager
        self._session_id = session_id
        self._store = store

    def bind_store(self, store: AioSQLiteSubagentStore | None) -> None:
        self._store = store

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
        if status is not None:
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
        if self._store is None:
            return {"error": f"Unknown subagent task_id: {task_id}"}
        persisted = await self._store.get_run(task_id)
        if persisted is None or (
            self._session_id is not None and persisted.get("parent_session_id") != self._session_id
        ):
            return {"error": f"Unknown subagent task_id: {task_id}"}
        if persisted.get("phase") in {"done", "error", "cancelled"}:
            return {
                "completed": True,
                "result": _serialize_persisted_result(persisted),
            }
        return {
            "completed": False,
            "status": _serialize_persisted_status(persisted, tail_tool_events=5),
        }
