"""FastAPI chat endpoints for the picobot runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from simplified_chatbot.agent.types import ContentBlock, MessageContent
from simplified_chatbot.runtime.local_runtime import ModelNotAllowedError
from simplified_chatbot.server.common import error_response, get_request_id, get_runtime
from simplified_chatbot.server.schemas import (
    ChatImageInput,
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
    runtime = get_runtime(request)
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
        model_override=payload.model,
    )


def _build_chat_stream_response(
    request: Request,
    *,
    session_id: str,
    message: MessageContent,
    model_override: str | None = None,
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
            result = await runtime.handle_input_stream_async(
                session_id,
                message,
                on_delta=on_delta,
                model_override=model_override,
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
        except ModelNotAllowedError as exc:
            await queue.put(
                {
                    "event": "error",
                    "data": {
                        "code": "MODEL_NOT_ALLOWED",
                        "message": str(exc),
                        "request_id": request_id,
                    },
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
