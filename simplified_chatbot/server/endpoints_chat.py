"""FastAPI chat endpoints for the picobot runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from simplified_chatbot.server.common import error_response, get_request_id, get_runtime
from simplified_chatbot.server.schemas import (
    ChatRequest,
    ChatResponse,
    ChatStreamRequest,
    ChatStreamDone,
    ChatTraceEvent,
)
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    """Return one complete assistant response."""
    runtime = get_runtime(request)
    events: list[ChatTraceEvent] = []

    def on_event(event: str, data: dict[str, Any]) -> None:
        events.append(ChatTraceEvent(event=event, data=data))

    try:
        result = await runtime.handle_message_async(
            payload.session_id,
            payload.message,
            on_event=on_event,
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
) -> StreamingResponse:
    """Stream one assistant response using SSE."""
    return _build_chat_stream_response(
        request,
        session_id=session_id,
        message=message,
    )


@router.post("/chat/stream")
async def chat_stream_post(
    request: Request,
    payload: ChatStreamRequest,
) -> StreamingResponse:
    """Stream one assistant response using SSE with a JSON request body."""
    return _build_chat_stream_response(
        request,
        session_id=payload.session_id,
        message=payload.message,
    )


def _build_chat_stream_response(
    request: Request,
    *,
    session_id: str,
    message: str,
) -> StreamingResponse:
    """Build the shared SSE response for GET/POST stream endpoints."""
    runtime = get_runtime(request)
    request_id = get_request_id(request)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_delta(delta: str) -> None:
        queue.put_nowait({"event": "delta", "data": delta})

    def on_event(event: str, data: dict[str, Any]) -> None:
        queue.put_nowait({"event": event, "data": data})

    async def produce() -> None:
        try:
            result = await runtime.handle_message_stream_async(
                session_id,
                message,
                on_delta=on_delta,
                on_event=on_event,
            )
            await queue.put(
                {
                    "event": "done",
                    "data": ChatStreamDone(
                        session_id=session_id,
                        content=result.content,
                        usage=result.usage,
                        tools_used=result.tools_used,
                        stop_reason=result.stop_reason,
                    ).model_dump(),
                },
            )
        except ValueError as exc:
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "code": "MESSAGE_INVALID",
                        "message": str(exc),
                        "request_id": request_id,
                    },
                },
            )
        except Exception as exc:
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "code": "INTERNAL_ERROR",
                        "message": str(exc),
                        "request_id": request_id,
                    },
                },
            )

    async def stream() -> Any:
        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                yield encode_sse(event=str(item["event"]), data=item["data"])
                if item["event"] in {"done", "error"}:
                    break
        finally:
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
