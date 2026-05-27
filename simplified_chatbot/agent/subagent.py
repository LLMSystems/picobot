"""Background subagent orchestration primitives."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol


class SupportsAsyncRun(Protocol):
    """Minimal chatbot protocol required by the subagent manager."""

    async def run_async(
        self,
        message: str,
        *,
        history: list[dict[str, Any]] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Any:
        """Execute one async agent run."""

    async def run_stream_async(
        self,
        message: str,
        *args: Any,
        history: list[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> Any:
        """Execute one streamed async agent run when supported."""


ChatbotFactory = Callable[[Path | None, str | None], SupportsAsyncRun]
SubagentResultCallback = Callable[
    ["SubagentStatus", "SubagentResult"],
    Awaitable[None] | None,
]
SubagentEventCallback = Callable[
    ["SubagentStatus", str, dict[str, Any]],
    Awaitable[None] | None,
]
SubagentSpawnCallback = Callable[
    ["SubagentStatus"],
    Awaitable[None] | None,
]


@dataclass(slots=True)
class SubagentSpec:
    """Configuration for one spawned subagent task."""

    task: str
    label: str | None = None
    temperature: float | None = None
    workspace: Path | None = None
    model_override: str | None = None
    parent_session_id: str | None = None


@dataclass(slots=True)
class SubagentStatus:
    """Current observable state of a spawned subagent."""

    task_id: str
    label: str
    task: str
    started_at: float
    started_at_utc: str = field(default_factory=lambda: _utc_timestamp())
    workspace: Path | None = None
    parent_session_id: str | None = None
    phase: str = "initializing"
    iteration: int = 0
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str | None = None
    error: str | None = None


@dataclass(slots=True)
class SubagentResult:
    """Final result for one completed subagent task."""

    task_id: str
    ok: bool
    content: str
    stop_reason: str
    workspace: Path | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class SubagentManager:
    """Manage background subagent execution and result collection."""

    def __init__(
        self,
        chatbot_factory: ChatbotFactory,
        *,
        max_concurrent_subagents: int = 1,
        spawn_callback: SubagentSpawnCallback | None = None,
        event_callback: SubagentEventCallback | None = None,
        result_callback: SubagentResultCallback | None = None,
    ) -> None:
        if max_concurrent_subagents < 1:
            raise ValueError("max_concurrent_subagents must be >= 1")
        self._chatbot_factory = chatbot_factory
        self.max_concurrent_subagents = max_concurrent_subagents
        self._spawn_callback = spawn_callback
        self._event_callback = event_callback
        self._result_callback = result_callback
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._statuses: dict[str, SubagentStatus] = {}
        self._results: dict[str, SubagentResult] = {}
        self._done_events: dict[str, asyncio.Event] = {}

    async def spawn(
        self,
        spec: SubagentSpec,
        *,
        parent_workspace: Path | None = None,
    ) -> str:
        """Start one background subagent task and return its task id."""
        if self.get_running_count() >= self.max_concurrent_subagents:
            raise RuntimeError(
                "subagent concurrency limit reached "
                f"({self.get_running_count()}/{self.max_concurrent_subagents})"
            )
        task_text = spec.task.strip()
        if not task_text:
            raise ValueError("task must not be empty")

        task_id = self._generate_task_id()
        label = self._derive_label(spec)
        status = SubagentStatus(
            task_id=task_id,
            label=label,
            task=task_text,
            started_at=time.monotonic(),
            parent_session_id=spec.parent_session_id,
        )
        status.workspace = self._resolve_workspace(
            task_id,
            spec,
            parent_workspace=parent_workspace,
        )
        self._statuses[task_id] = status
        self._done_events[task_id] = asyncio.Event()
        try:
            await self._invoke_spawn_callback(status)
            await self._emit_event(
                status,
                "subagent_spawned",
                {
                    "task_id": status.task_id,
                    "label": status.label,
                    "task": status.task,
                    "workspace": str(status.workspace) if status.workspace is not None else None,
                },
            )
        except Exception:
            self._statuses.pop(task_id, None)
            self._done_events.pop(task_id, None)
            raise
        task = asyncio.create_task(self._run_subagent(task_id, spec), name=f"subagent:{task_id}")
        self._running_tasks[task_id] = task
        task.add_done_callback(lambda finished: self._on_task_done(task_id, finished))
        return task_id

    async def wait(self, task_id: str) -> SubagentResult:
        """Wait for one subagent to finish and return its final result."""
        if task_id not in self._statuses:
            raise KeyError(task_id)
        done = self._done_events[task_id]
        await done.wait()
        return self._results[task_id]

    def get_status(self, task_id: str) -> SubagentStatus | None:
        """Return the current status for one task."""
        return self._statuses.get(task_id)

    def list_running(self) -> list[SubagentStatus]:
        """Return statuses for tasks that are still running."""
        return [
            self._statuses[task_id]
            for task_id, task in self._running_tasks.items()
            if not task.done() and task_id in self._statuses
        ]

    def list_statuses(
        self,
        *,
        phase: str | None = None,
        include_completed: bool = True,
        limit: int | None = None,
    ) -> list[SubagentStatus]:
        """Return known subagent statuses with optional filtering."""
        items = sorted(
            self._statuses.values(),
            key=lambda status: status.started_at,
            reverse=True,
        )
        if not include_completed:
            items = [item for item in items if item.phase not in _TERMINAL_PHASES]
        if phase is not None:
            items = [item for item in items if item.phase == phase]
        if limit is not None:
            items = items[:limit]
        return items

    async def cancel(self, task_id: str) -> bool:
        """Cancel one running subagent task."""
        task = self._running_tasks.get(task_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return True

    def get_running_count(self) -> int:
        """Return the number of subagents currently running."""
        return sum(1 for task in self._running_tasks.values() if not task.done())

    def get_result(self, task_id: str) -> SubagentResult | None:
        """Return a cached final result when available."""
        return self._results.get(task_id)

    def bind_result_callback(
        self,
        callback: SubagentResultCallback,
    ) -> None:
        """Append one result callback while preserving any existing callback."""
        existing = self._result_callback
        if existing is None:
            self._result_callback = callback
            return

        async def chained(
            status: SubagentStatus,
            result: SubagentResult,
        ) -> None:
            first = existing(status, result)
            if asyncio.iscoroutine(first):
                await first
            second = callback(status, result)
            if asyncio.iscoroutine(second):
                await second

        self._result_callback = chained

    def bind_spawn_callback(
        self,
        callback: SubagentSpawnCallback,
    ) -> None:
        """Append one spawn callback while preserving any existing callback."""
        existing = self._spawn_callback
        if existing is None:
            self._spawn_callback = callback
            return

        async def chained(status: SubagentStatus) -> None:
            first = existing(status)
            if asyncio.iscoroutine(first):
                await first
            second = callback(status)
            if asyncio.iscoroutine(second):
                await second

        self._spawn_callback = chained

    def bind_event_callback(
        self,
        callback: SubagentEventCallback,
    ) -> None:
        """Append one event callback while preserving any existing callback."""
        existing = self._event_callback
        if existing is None:
            self._event_callback = callback
            return

        async def chained(
            status: SubagentStatus,
            event: str,
            payload: dict[str, Any],
        ) -> None:
            first = existing(status, event, payload)
            if asyncio.iscoroutine(first):
                await first
            second = callback(status, event, payload)
            if asyncio.iscoroutine(second):
                await second

        self._event_callback = chained

    async def wait_for(
        self,
        task_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> SubagentResult | None:
        """Wait for a subagent, optionally returning None on timeout."""
        if timeout_seconds is None:
            return await self.wait(task_id)
        if task_id not in self._statuses:
            raise KeyError(task_id)
        try:
            return await asyncio.wait_for(
                self.wait(task_id),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            return None

    def _on_task_done(self, task_id: str, task: asyncio.Task[None]) -> None:
        self._running_tasks.pop(task_id, None)
        if task_id in self._results:
            self._done_events[task_id].set()
            return
        if task.cancelled():
            status = self._statuses[task_id]
            status.phase = "cancelled"
            status.stop_reason = "cancelled"
            result = SubagentResult(
                task_id=task_id,
                ok=False,
                content="Cancelled",
                stop_reason="cancelled",
                workspace=status.workspace,
                tool_events=list(status.tool_events),
            )
            self._queue_fallback_result(status, result)
            return
        exc = task.exception()
        if exc is not None:
            status = self._statuses[task_id]
            status.phase = "error"
            status.error = str(exc)
            status.stop_reason = "error"
            result = SubagentResult(
                task_id=task_id,
                ok=False,
                content=f"Error: {exc}",
                stop_reason="error",
                workspace=status.workspace,
                tool_events=list(status.tool_events),
                error=str(exc),
            )
            self._queue_fallback_result(status, result)

    async def _run_subagent(self, task_id: str, spec: SubagentSpec) -> None:
        status = self._statuses[task_id]
        status.phase = "running"
        chatbot = self._chatbot_factory(spec.workspace, spec.model_override)
        pending_event_tasks: set[asyncio.Task[None]] = set()
        event_chain: asyncio.Task[None] | None = None

        def schedule_event(event: str, payload: dict[str, Any]) -> None:
            nonlocal event_chain
            previous = event_chain

            async def emit_in_order() -> None:
                if previous is not None:
                    await previous
                await self._emit_event(status, event, payload)

            task = asyncio.create_task(emit_in_order())
            pending_event_tasks.add(task)
            task.add_done_callback(lambda finished: pending_event_tasks.discard(finished))
            event_chain = task

        async def drain_pending_events() -> None:
            if not pending_event_tasks:
                return
            await asyncio.gather(*list(pending_event_tasks), return_exceptions=True)

        await self._emit_event(
            status,
            "subagent_phase_changed",
            {"phase": "running"},
        )

        def on_event(event: str, data: dict[str, Any]) -> None:
            self._update_status_from_event(status, event, data)
            event_name = _SUBAGENT_EVENT_MAP.get(event)
            if event_name is None:
                return
            schedule_event(event_name, dict(data))

        def on_delta(delta: str) -> None:
            schedule_event("subagent_delta", {"delta": delta})

        try:
            run_stream_async = getattr(chatbot, "run_stream_async", None)
            if callable(run_stream_async):
                run_result = await run_stream_async(
                    spec.task,
                    model_override=spec.model_override,
                    on_event=on_event,
                    on_delta=on_delta,
                )
            else:
                run_result = await chatbot.run_async(
                    spec.task,
                    model_override=spec.model_override,
                    on_event=on_event,
                )
        except asyncio.CancelledError:
            status.phase = "cancelled"
            status.stop_reason = "cancelled"
            result = SubagentResult(
                task_id=task_id,
                ok=False,
                content="Cancelled",
                stop_reason="cancelled",
                workspace=status.workspace,
                tool_events=list(status.tool_events),
            )
            await drain_pending_events()
            await self._complete_task(status, result)
            raise
        except Exception as exc:
            status.phase = "error"
            status.error = str(exc)
            status.stop_reason = "error"
            result = SubagentResult(
                task_id=task_id,
                ok=False,
                content=f"Error: {exc}",
                stop_reason="error",
                workspace=status.workspace,
                tool_events=list(status.tool_events),
                error=str(exc),
            )
            await drain_pending_events()
            await self._complete_task(status, result)
            return

        result = self._build_subagent_result(task_id, run_result, status)
        status.phase = "done" if result.ok else "error"
        status.stop_reason = result.stop_reason
        if not status.usage:
            status.usage = dict(result.usage)
        status.error = result.error
        await drain_pending_events()
        await self._complete_task(status, result)

    @staticmethod
    def _generate_task_id() -> str:
        return f"sub_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _resolve_workspace(
        task_id: str,
        spec: SubagentSpec,
        *,
        parent_workspace: Path | None,
    ) -> Path | None:
        base_workspace = (
            parent_workspace.expanduser().resolve()
            if parent_workspace is not None
            else None
        )
        if spec.workspace is not None:
            candidate = spec.workspace.expanduser()
            if not candidate.is_absolute() and base_workspace is not None:
                candidate = base_workspace / candidate
            workspace = candidate.resolve()
        elif base_workspace is not None:
            workspace = base_workspace / ".subagents" / task_id
        else:
            return None
        workspace.mkdir(parents=True, exist_ok=True)
        spec.workspace = workspace
        return workspace

    @staticmethod
    def _derive_label(spec: SubagentSpec) -> str:
        if spec.label and spec.label.strip():
            return spec.label.strip()
        text = " ".join(spec.task.split()).strip()
        if len(text) <= 30:
            return text
        return text[:30] + "..."

    @staticmethod
    def _build_subagent_result(
        task_id: str,
        run_result: Any,
        status: SubagentStatus,
    ) -> SubagentResult:
        content = str(getattr(run_result, "content", "") or "")
        stop_reason = str(getattr(run_result, "stop_reason", "completed") or "completed")
        usage = getattr(run_result, "usage", {}) or {}
        error = getattr(run_result, "error", None)
        tool_events = list(status.tool_events)
        ok = stop_reason in _SUCCESS_STOP_REASONS and not error
        return SubagentResult(
            task_id=task_id,
            ok=ok,
            content=content,
            stop_reason=stop_reason,
            workspace=status.workspace,
            usage=dict(usage) if isinstance(usage, dict) else {},
            tool_events=tool_events,
            error=str(error) if error else None,
        )

    async def _complete_task(
        self,
        status: SubagentStatus,
        result: SubagentResult,
    ) -> None:
        self._results[status.task_id] = result
        await self._emit_terminal_event(status, result)
        await self._invoke_result_callback(status, result)
        self._done_events[status.task_id].set()

    async def _invoke_result_callback(
        self,
        status: SubagentStatus,
        result: SubagentResult,
    ) -> None:
        if self._result_callback is None:
            return
        callback_result = self._result_callback(status, result)
        if asyncio.iscoroutine(callback_result):
            await callback_result

    async def _invoke_spawn_callback(self, status: SubagentStatus) -> None:
        if self._spawn_callback is None:
            return
        callback_result = self._spawn_callback(status)
        if asyncio.iscoroutine(callback_result):
            await callback_result

    async def _emit_terminal_event(
        self,
        status: SubagentStatus,
        result: SubagentResult,
    ) -> None:
        await self._emit_event(
            status,
            "subagent_phase_changed",
            {
                "phase": status.phase,
                "stop_reason": status.stop_reason,
                "ok": result.ok,
            },
        )
        terminal_event = "subagent_completed"
        if status.phase == "error":
            terminal_event = "subagent_failed"
        elif status.phase == "cancelled":
            terminal_event = "subagent_cancelled"
        await self._emit_event(
            status,
            terminal_event,
            {
                "ok": result.ok,
                "stop_reason": result.stop_reason,
                "content": result.content,
                "error": result.error,
                "usage": dict(result.usage),
            },
        )

    async def _emit_event(
        self,
        status: SubagentStatus,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        if self._event_callback is None:
            return
        callback_result = self._event_callback(status, event, payload)
        if asyncio.iscoroutine(callback_result):
            await callback_result

    def _queue_fallback_result(
        self,
        status: SubagentStatus,
        result: SubagentResult,
    ) -> None:
        async def finalize() -> None:
            await self._complete_task(status, result)

        asyncio.create_task(finalize())

    @staticmethod
    def _update_status_from_event(status: SubagentStatus, event: str, data: dict[str, Any]) -> None:
        if event == "tool_call_started":
            tool_event = {
                "id": data.get("id"),
                "name": data.get("name"),
                "status": "running",
                "detail": data.get("arguments", {}),
            }
            status.tool_events.append(tool_event)
            return
        if event == "tool_call_finished":
            call_id = data.get("id")
            for item in reversed(status.tool_events):
                if item.get("id") == call_id:
                    item["status"] = "ok" if data.get("ok") else "failed"
                    item["result"] = data.get("result")
                    if not data.get("ok"):
                        status.error = str(data.get("error") or "tool execution failed")
                    break
            else:
                status.tool_events.append(
                    {
                        "id": call_id,
                        "name": data.get("name"),
                        "status": "ok" if data.get("ok") else "failed",
                        "result": data.get("result"),
                    },
                )
            return
        if event == "iteration_completed":
            iteration = data.get("iteration")
            if isinstance(iteration, int):
                status.iteration = iteration
            usage = data.get("usage")
            if isinstance(usage, dict):
                status.usage = dict(usage)


_TERMINAL_PHASES = frozenset({"done", "error", "cancelled"})
_SUCCESS_STOP_REASONS = frozenset({"completed", "stop"})
_SUBAGENT_EVENT_MAP = {
    "tool_call_started": "subagent_tool_call_started",
    "tool_call_finished": "subagent_tool_call_finished",
    "iteration_completed": "subagent_iteration_completed",
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
