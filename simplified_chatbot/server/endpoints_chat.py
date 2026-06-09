"""FastAPI chat endpoints for the picobot runtime."""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from simplified_chatbot.agent.types import ContentBlock, MessageContent
from simplified_chatbot.auth.users_store import User
from simplified_chatbot.runtime.local_runtime import ModelNotAllowedError
from simplified_chatbot.server.common import error_response, get_request_id, get_runtime
from simplified_chatbot.server.deps import claim_or_check_session, require_user
from simplified_chatbot.server.schemas import (
    AskUserQuestionAnswerRequest,
    AskUserQuestionAnswerResponse,
    ChatImageInput,
    ChatRequest,
    ChatResponse,
    ChatStreamRequest,
    ChatStreamDone,
    ChatTraceEvent,
)
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()

logger = logging.getLogger(__name__)

_CHAT_STREAM_QUEUE_MAX_SIZE = 64
_CHAT_STREAM_DELTA_FLUSH_INTERVAL_SECONDS = 0.03
_CHAT_STREAM_DELTA_FLUSH_BYTES = 512
_CHAT_STREAM_KEEPALIVE_SECONDS = 15.0
_TRACE_EVENTS = {
    "llm_call_finished",
    "memory_compaction_failed",
    "memory_compaction_finished",
    "memory_compaction_skipped",
    "memory_compaction_started",
    "reasoning_delta",
    "run_started",
    "tool_call_finished",
    "tool_call_started",
    "workspace_changed",
}


class _StreamEventQueue:
    """Bounded async queue that merges delta events under pressure."""

    def __init__(self, *, max_size: int) -> None:
        self._items: deque[dict[str, Any]] = deque()
        self._has_items = asyncio.Event()
        self._max_size = max(1, max_size)
        self.dropped_trace_events = 0

    def put(
        self,
        item: dict[str, Any],
        *,
        critical: bool = False,
        trace: bool = False,
    ) -> None:
        if item.get("event") == "delta":
            self._put_delta(str(item.get("data") or ""))
            return

        if len(self._items) >= self._max_size:
            if trace and not critical:
                self.dropped_trace_events += 1
                return
            self._make_room_for_critical()

        if len(self._items) >= self._max_size and not critical:
            self.dropped_trace_events += 1
            return

        self._items.append(dict(item))
        self._has_items.set()

    async def get(self) -> dict[str, Any]:
        while not self._items:
            self._has_items.clear()
            await self._has_items.wait()
        item = self._items.popleft()
        if not self._items:
            self._has_items.clear()
        return item

    def _put_delta(self, delta: str) -> None:
        if not delta:
            return

        if self._merge_into_last_delta(delta):
            self._has_items.set()
            return

        if len(self._items) >= self._max_size and self._merge_into_any_delta(delta):
            self._has_items.set()
            return

        if len(self._items) >= self._max_size:
            self._drop_one_trace_event()

        if len(self._items) >= self._max_size:
            self._merge_into_last_event_or_append(delta)
            self._has_items.set()
            return

        self._items.append({"event": "delta", "data": delta})
        self._has_items.set()

    def _merge_into_last_delta(self, delta: str) -> bool:
        if not self._items or self._items[-1].get("event") != "delta":
            return False
        self._items[-1]["data"] = str(self._items[-1].get("data") or "") + delta
        return True

    def _merge_into_any_delta(self, delta: str) -> bool:
        for item in reversed(self._items):
            if item.get("event") == "delta":
                item["data"] = str(item.get("data") or "") + delta
                return True
        return False

    def _merge_into_last_event_or_append(self, delta: str) -> None:
        if self._items:
            last = self._items[-1]
            if last.get("event") == "delta":
                last["data"] = str(last.get("data") or "") + delta
                return
        self._items.append({"event": "delta", "data": delta})

    def _drop_one_trace_event(self) -> bool:
        for index, item in enumerate(self._items):
            if item.get("event") in _TRACE_EVENTS:
                del self._items[index]
                self.dropped_trace_events += 1
                return True
        return False

    def _make_room_for_critical(self) -> None:
        while len(self._items) >= self._max_size:
            if self._drop_one_trace_event():
                continue
            if self._merge_adjacent_deltas():
                continue
            # Preserve terminal delivery even if that means dropping old metadata.
            self._items.popleft()
            break

    def _merge_adjacent_deltas(self) -> bool:
        previous: dict[str, Any] | None = None
        for item in list(self._items):
            if (
                previous is not None
                and previous.get("event") == "delta"
                and item.get("event") == "delta"
            ):
                previous["data"] = (
                    str(previous.get("data") or "")
                    + str(item.get("data") or "")
                )
                self._items.remove(item)
                return True
            previous = item
        return False


class _ChatStreamBuffer:
    """Coalesce small deltas before they reach the SSE event queue."""

    def __init__(
        self,
        queue: _StreamEventQueue,
        *,
        loop: asyncio.AbstractEventLoop,
        flush_interval_seconds: float,
        flush_bytes: int,
    ) -> None:
        self._queue = queue
        self._loop = loop
        self._flush_interval_seconds = max(0.0, flush_interval_seconds)
        self._flush_bytes = max(1, flush_bytes)
        self._delta_parts: list[str] = []
        self._delta_bytes = 0
        self._flush_handle: asyncio.TimerHandle | None = None
        self._payload_delta_buffers: dict[str, dict[str, Any]] = {}

    def put_delta(self, delta: str) -> None:
        if not delta:
            return
        self.flush_payload_delta_events()
        self._delta_parts.append(delta)
        self._delta_bytes += len(delta.encode("utf-8"))
        if self._delta_bytes >= self._flush_bytes:
            self.flush_delta()
            return
        if self._flush_handle is None and self._flush_interval_seconds > 0:
            self._flush_handle = self._loop.call_later(
                self._flush_interval_seconds,
                self.flush_delta,
            )

    def put_event(
        self,
        event: str,
        data: Any,
        *,
        critical: bool = False,
        trace: bool = False,
    ) -> None:
        if event != "delta":
            self.flush_all()
        self._queue.put(
            {"event": event, "data": data},
            critical=critical,
            trace=trace,
        )

    def put_payload_delta_event(
        self,
        event: str,
        data: dict[str, Any],
        *,
        critical: bool = False,
        trace: bool = False,
    ) -> None:
        delta = data.get("delta")
        if not isinstance(delta, str) or not delta:
            self.put_event(event, data, critical=critical, trace=trace)
            return
        self.flush_delta()
        buffer = self._payload_delta_buffers.get(event)
        if buffer is None:
            buffer = {
                "parts": [],
                "bytes": 0,
                "template": dict(data),
                "handle": None,
                "critical": critical,
                "trace": trace,
            }
            self._payload_delta_buffers[event] = buffer
        buffer["parts"].append(delta)
        buffer["bytes"] += len(delta.encode("utf-8"))
        buffer["template"] = {**dict(data), "delta": ""}
        buffer["critical"] = bool(buffer["critical"] or critical)
        buffer["trace"] = bool(buffer["trace"] or trace)
        if int(buffer["bytes"]) >= self._flush_bytes:
            self.flush_payload_delta_event(event)
            return
        if buffer["handle"] is None and self._flush_interval_seconds > 0:
            buffer["handle"] = self._loop.call_later(
                self._flush_interval_seconds,
                self.flush_payload_delta_event,
                event,
            )

    def flush_delta(self) -> None:
        self._cancel_flush_timer()
        if not self._delta_parts:
            return
        payload = "".join(self._delta_parts)
        self._delta_parts = []
        self._delta_bytes = 0
        self._queue.put({"event": "delta", "data": payload})

    def close(self) -> None:
        self.flush_all()
        self._cancel_flush_timer()

    def flush_all(self) -> None:
        self.flush_delta()
        self.flush_payload_delta_events()

    def flush_payload_delta_events(self) -> None:
        for event in list(self._payload_delta_buffers):
            self.flush_payload_delta_event(event)

    def flush_payload_delta_event(self, event: str) -> None:
        buffer = self._payload_delta_buffers.pop(event, None)
        if buffer is None:
            return
        handle = buffer.get("handle")
        if handle is not None and not handle.cancelled():
            handle.cancel()
        parts = buffer.get("parts") or []
        if not parts:
            return
        payload = dict(buffer.get("template") or {})
        payload["delta"] = "".join(str(part) for part in parts)
        self._queue.put(
            {"event": event, "data": payload},
            critical=bool(buffer.get("critical")),
            trace=bool(buffer.get("trace")),
        )

    def _cancel_flush_timer(self) -> None:
        handle = self._flush_handle
        self._flush_handle = None
        if handle is not None and not handle.cancelled():
            handle.cancel()


async def _record_chat_usage(
    request: Request,
    *,
    session_id: str,
    model: str | None,
    usage: dict[str, int] | None,
) -> None:
    """Push a chat-call usage record into the metrics layer, if available.

    Delegates to `MetricsService.record_chat_usage` which writes both the
    in-memory ring (for cheap reads in tests) and the persistent
    `chat_usage_events` table (so totals survive process restarts).
    """
    svc = getattr(request.app.state, "metrics", None)
    if svc is None:
        return
    try:
        await svc.record_chat_usage(
            session_id=session_id, model=model, usage=usage,
        )
    except Exception:
        # Recording must never break the chat flow.
        pass


async def _record_llm_calls(
    request: Request,
    *,
    session_id: str,
    chat_id: str | None,
    items: list[dict[str, Any]],
) -> None:
    """Drain the buffered `llm_call_finished` events into the metrics layer.

    Buffering during the run + flushing here means a single multi-iteration
    chat call records all of its provider calls without blocking the SSE/HTTP
    hot path or leaking fire-and-forget tasks. Flushed in one batch via
    `record_llm_calls_many` — N iterations become 1 transaction + 1 fsync
    instead of N.

    `chat_id` groups all LLM calls in one user turn — feeds the
    iterations-per-chat aggregation.
    """
    if not items:
        return
    filtered = [
        data for data in items
        if str(data.get("purpose") or "") != "memory_compaction"
    ]
    if not filtered:
        return
    svc = getattr(request.app.state, "metrics", None)
    batch_record = getattr(svc, "record_llm_calls_many", None)
    if not callable(batch_record):
        return
    payload = [
        {
            "session_id": session_id,
            "chat_id": chat_id,
            "model": data.get("model"),
            "latency_ms": int(data.get("latency_ms") or 0),
            "success": bool(data.get("success", True)),
            "error_type": data.get("error_type"),
            "ttft_ms": (
                int(data["ttft_ms"]) if data.get("ttft_ms") is not None else None
            ),
        }
        for data in filtered
    ]
    try:
        await batch_record(payload)
    except Exception:
        pass


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    payload: ChatRequest,
    user: User = Depends(require_user),
) -> ChatResponse:
    """Return one complete assistant response."""
    runtime = get_runtime(request)
    denied = await claim_or_check_session(request, payload.session_id, user)
    if denied is not None:
        return denied
    # Reuse the per-request id middleware as the chat_id so all LLM iterations
    # in this turn share a grouping key (drives iterations-per-chat metric).
    chat_id = get_request_id(request)
    events: list[ChatTraceEvent] = []
    llm_events: list[dict[str, Any]] = []

    def on_event(event: str, data: dict[str, Any]) -> None:
        events.append(ChatTraceEvent(event=event, data=data))
        if event == "llm_call_finished":
            llm_events.append(data)

    try:
        try:
            content = await _build_chat_content(
                runtime,
                session_id=payload.session_id,
                message=payload.message,
                images=payload.images,
            )
            result = await runtime.handle_input_async(
                payload.session_id,
                content,
                model_override=payload.model,
                subagent_model_override=payload.subagent_model,
                temperature_override=payload.temperature,
                max_tokens_override=payload.max_tokens,
                max_iterations_override=payload.max_iterations,
                system_prompt_override=payload.system_prompt,
                disabled_tools=payload.disabled_tools,
                on_event=on_event,
            )
        except ModelNotAllowedError as exc:
            return error_response(
                request,
                status_code=400,
                code="MODEL_NOT_ALLOWED",
                message=str(exc),
            )
        except KeyError:
            return error_response(
                request,
                status_code=404,
                code="SESSION_NOT_FOUND",
                message=f"Session '{payload.session_id}' not found",
            )
        except FileNotFoundError as exc:
            return error_response(
                request,
                status_code=404,
                code="WORKSPACE_FILE_NOT_FOUND",
                message=str(exc),
            )
        except IsADirectoryError as exc:
            return error_response(
                request,
                status_code=400,
                code="WORKSPACE_NOT_A_FILE",
                message=str(exc),
            )
        except ValueError as exc:
            return error_response(
                request,
                status_code=400,
                code="MESSAGE_INVALID",
                message=str(exc),
            )
        except RuntimeError as exc:
            return error_response(
                request,
                status_code=500,
                code="RUNTIME_ERROR",
                message=str(exc),
            )
    finally:
        # Always flush LLM call records — even on early-return error paths the
        # provider may have been called (e.g. one good iteration before a
        # tool-validation failure).
        await _record_llm_calls(
            request,
            session_id=payload.session_id,
            chat_id=chat_id,
            items=llm_events,
        )

    await _record_chat_usage(
        request,
        session_id=payload.session_id,
        model=getattr(result, "model", None),
        usage=result.usage,
    )
    return ChatResponse(
        session_id=payload.session_id,
        content=result.content,
        usage=result.usage,
        tools_used=result.tools_used,
        stop_reason=result.stop_reason,
        events=events,
    )


@router.get("/chat/stream")
async def chat_stream(
    request: Request,
    session_id: str = Query(min_length=1),
    message: str = Query(min_length=1),
    include_trace: bool = Query(default=True),
    user: User = Depends(require_user),
) -> StreamingResponse:
    """Stream one assistant response using SSE."""
    denied = await claim_or_check_session(request, session_id, user)
    if denied is not None:
        return denied
    return _build_chat_stream_response(
        request,
        session_id=session_id,
        message=message,
        include_trace=include_trace,
    )


@router.post("/chat/stream")
async def chat_stream_post(
    request: Request,
    payload: ChatStreamRequest,
    user: User = Depends(require_user),
) -> StreamingResponse:
    """Stream one assistant response using SSE with a JSON request body."""
    runtime = get_runtime(request)
    denied = await claim_or_check_session(request, payload.session_id, user)
    if denied is not None:
        return denied
    try:
        content = await _build_chat_content(
            runtime,
            session_id=payload.session_id,
            message=payload.message,
            images=payload.images,
        )
    except KeyError:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{payload.session_id}' not found",
        )
    except FileNotFoundError as exc:
        return error_response(
            request,
            status_code=404,
            code="WORKSPACE_FILE_NOT_FOUND",
            message=str(exc),
        )
    except IsADirectoryError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_NOT_A_FILE",
            message=str(exc),
        )
    except ValueError as exc:
        return error_response(
            request,
            status_code=400,
            code="MESSAGE_INVALID",
            message=str(exc),
        )
    return _build_chat_stream_response(
        request,
        session_id=payload.session_id,
        message=content,
        include_trace=payload.include_trace,
        model_override=payload.model,
        subagent_model_override=payload.subagent_model,
        temperature_override=payload.temperature,
        max_tokens_override=payload.max_tokens,
        max_iterations_override=payload.max_iterations,
        system_prompt_override=payload.system_prompt,
        disabled_tools=payload.disabled_tools,
    )


def _build_chat_stream_response(
    request: Request,
    *,
    session_id: str,
    message: MessageContent,
    model_override: str | None = None,
    subagent_model_override: str | None = None,
    temperature_override: float | None = None,
    max_tokens_override: int | None = None,
    max_iterations_override: int | None = None,
    system_prompt_override: str | None = None,
    disabled_tools: list[str] | None = None,
    include_trace: bool = True,
) -> StreamingResponse:
    """Build the shared SSE response for GET/POST stream endpoints."""
    runtime = get_runtime(request)
    request_id = get_request_id(request)
    queue = _StreamEventQueue(max_size=_CHAT_STREAM_QUEUE_MAX_SIZE)
    stream_buffer = _ChatStreamBuffer(
        queue,
        loop=asyncio.get_running_loop(),
        flush_interval_seconds=_CHAT_STREAM_DELTA_FLUSH_INTERVAL_SECONDS,
        flush_bytes=_CHAT_STREAM_DELTA_FLUSH_BYTES,
    )
    llm_events: list[dict[str, Any]] = []

    def on_delta(delta: str) -> None:
        stream_buffer.put_delta(delta)

    def on_event(event: str, data: dict[str, Any]) -> None:
        if event == "llm_call_finished":
            llm_events.append(data)
        if include_trace:
            if event == "reasoning_delta":
                stream_buffer.put_payload_delta_event(
                    event,
                    data,
                    trace=True,
                )
                return
            stream_buffer.put_event(
                event,
                data,
                trace=event in _TRACE_EVENTS,
            )

    async def produce() -> None:
        # Defer the terminal queue.put until AFTER the LLM-event flush:
        # stream()'s `task.cancel()` fires the moment the consumer sees a
        # done/error event, and would otherwise interrupt the DB write
        # mid-flight (CancelledError bypasses our broad except blocks).
        terminal: dict[str, Any] | None = None
        try:
            if not include_trace:
                stream_buffer.put_event(
                    "started",
                    {"session_id": session_id, "request_id": request_id},
                    critical=True,
                )
            result = await runtime.handle_input_stream_async(
                session_id,
                message,
                on_delta=on_delta,
                model_override=model_override,
                subagent_model_override=subagent_model_override,
                temperature_override=temperature_override,
                max_tokens_override=max_tokens_override,
                max_iterations_override=max_iterations_override,
                system_prompt_override=system_prompt_override,
                disabled_tools=disabled_tools,
                on_event=on_event,
            )
            await _record_chat_usage(
                request,
                session_id=session_id,
                model=getattr(result, "model", None),
                usage=result.usage,
            )
            terminal = {
                "event": "done",
                "data": ChatStreamDone(
                    session_id=session_id,
                    content=result.content,
                    usage=result.usage,
                    tools_used=result.tools_used,
                    stop_reason=result.stop_reason,
                ).model_dump(),
            }
        except ModelNotAllowedError as exc:
            terminal = {
                "event": "error",
                "data": {
                    "code": "MODEL_NOT_ALLOWED",
                    "message": str(exc),
                    "request_id": request_id,
                },
            }
        except ValueError as exc:
            terminal = {
                "event": "error",
                "data": {
                    "code": "MESSAGE_INVALID",
                    "message": str(exc),
                    "request_id": request_id,
                },
            }
        except Exception as exc:
            logger.exception(
                "chat stream failed (session=%s request=%s): %s",
                session_id,
                request_id,
                exc,
            )
            terminal = {
                "event": "error",
                "data": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "request_id": request_id,
                },
            }

        await _record_llm_calls(
            request,
            session_id=session_id,
            chat_id=request_id,
            items=llm_events,
        )
        if terminal is not None:
            stream_buffer.put_event(
                str(terminal["event"]),
                terminal["data"],
                critical=True,
            )
        stream_buffer.close()

    metrics = getattr(request.app.state, "metrics", None)
    sse_counter = getattr(metrics, "sse_connections", None) if metrics else None

    async def stream() -> Any:
        task = asyncio.create_task(produce())
        if sse_counter is not None:
            sse_counter.enter("chat")
        try:
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(),
                        timeout=_CHAT_STREAM_KEEPALIVE_SECONDS,
                    )
                except asyncio.TimeoutError:
                    yield b": keepalive\n\n"
                    continue
                yield encode_sse(event=str(item["event"]), data=item["data"])
                if item["event"] in {"done", "error"}:
                    break
        finally:
            stream_buffer.close()
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            if sse_counter is not None:
                sse_counter.leave("chat")

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/ask_user_question/answer",
    response_model=AskUserQuestionAnswerResponse,
)
async def answer_ask_user_question(
    request: Request,
    session_id: str,
    payload: AskUserQuestionAnswerRequest,
) -> AskUserQuestionAnswerResponse:
    """Submit user answers to a pending ask_user_question tool call."""
    runtime = get_runtime(request)
    ok = await runtime.answer_ask_user_question(session_id, dict(payload.answers))
    if not ok:
        return error_response(
            request,
            status_code=404,
            code="NO_PENDING_QUESTION",
            message=f"No pending question for session '{session_id}'",
        )
    return AskUserQuestionAnswerResponse(ok=True)


async def _build_chat_content(
    runtime,
    *,
    session_id: str,
    message: str,
    images: list[ChatImageInput],
) -> MessageContent:
    if not images:
        return message

    blocks: list[ContentBlock] = [{"type": "text", "text": message}]
    for image in images:
        if image.url is not None:
            blocks.append(
                {
                    "type": "image",
                    "url": image.url,
                    "detail": image.detail,
                },
            )
            continue

        if image.path is None:
            raise ValueError("Each image must include path or url")
        _relative_path, target = await runtime.resolve_workspace_file_async(
            session_id,
            path=image.path,
        )
        blocks.append(
            {
                "type": "image",
                "path": str(target),
                "detail": image.detail,
            },
        )
    return blocks
