"""FastAPI chat endpoints for the picobot runtime."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from simplified_chatbot.server.common import get_runtime
from simplified_chatbot.server.schemas import ChatRequest, ChatResponse, ChatStreamDone
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse:
    """Return one complete assistant response."""
    runtime = get_runtime(request)
    try:
        result = await runtime.handle_message_async(
            payload.session_id,
            payload.message,
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    except RuntimeError as exc:
        return JSONResponse(
            status_code=500,
            content={"error": str(exc)},
        )

    return ChatResponse(
        session_id=payload.session_id,
        content=result.content,
        usage=result.usage,
        tools_used=result.tools_used,
        stop_reason=result.stop_reason,
    )


@router.get("/chat/stream")
async def chat_stream(
    request: Request,
    session_id: str = Query(min_length=1),
    message: str = Query(min_length=1),
) -> StreamingResponse:
    """Stream one assistant response using SSE."""
    runtime = get_runtime(request)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    def on_delta(delta: str) -> None:
        queue.put_nowait({"event": "delta", "data": delta})

    async def produce() -> None:
        try:
            result = await runtime.handle_message_stream_async(
                session_id,
                message,
                on_delta=on_delta,
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
            await queue.put({"event": "error", "data": {"error": str(exc)}})
        except Exception as exc:
            await queue.put({"event": "error", "data": {"error": str(exc)}})

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
