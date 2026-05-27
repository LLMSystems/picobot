"""FastAPI session and history endpoints for picobot."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import (
    DeleteSessionResponse,
    SessionCreateRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionRenameRequest,
    SessionSummary,
    SubagentEvent,
    SubagentEventsResponse,
    SubagentRun,
    SubagentRunListResponse,
)
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    """List known session ids."""
    runtime = get_runtime(request)
    sessions = [
        SessionSummary.model_validate(item)
        for item in await runtime.list_session_summaries_async()
    ]
    return SessionListResponse(sessions=sessions)


@router.post("/sessions", response_model=SessionSummary)
async def create_session(
    request: Request,
    payload: SessionCreateRequest,
) -> SessionSummary:
    """Create one empty session with optional title."""
    runtime = get_runtime(request)
    summary = await runtime.create_session_async(
        title=payload.title,
        session_id=payload.session_id,
    )
    return SessionSummary.model_validate(summary)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
async def get_session_messages(
    request: Request,
    session_id: str,
) -> SessionMessagesResponse:
    """Load one session's persisted message history."""
    runtime = get_runtime(request)
    messages = await runtime.load_history_async(session_id)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.get(
    "/sessions/{session_id}/subagents",
    response_model=SubagentRunListResponse,
)
async def list_session_subagents(
    request: Request,
    session_id: str,
    phase: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> SubagentRunListResponse:
    """List persisted subagent runs for one session."""
    runtime = get_runtime(request)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    items = [
        SubagentRun.model_validate(item)
        for item in await runtime.list_subagent_runs_async(
            session_id,
            phase=phase,
            limit=limit,
        )
    ]
    return SubagentRunListResponse(session_id=session_id, items=items)


@router.get(
    "/sessions/{session_id}/subagents/{task_id}",
    response_model=SubagentRun,
)
async def get_session_subagent(
    request: Request,
    session_id: str,
    task_id: str,
) -> SubagentRun:
    """Load one persisted subagent run for one session."""
    runtime = get_runtime(request)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    payload = await runtime.get_subagent_run_async(session_id, task_id)
    if payload is None:
        return error_response(
            request,
            status_code=404,
            code="SUBAGENT_NOT_FOUND",
            message=f"Subagent '{task_id}' not found in session '{session_id}'",
        )
    return SubagentRun.model_validate(payload)


@router.get(
    "/sessions/{session_id}/subagents/{task_id}/events",
    response_model=SubagentEventsResponse,
)
async def get_session_subagent_events(
    request: Request,
    session_id: str,
    task_id: str,
    after_seq: int | None = Query(default=None, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> SubagentEventsResponse:
    """Load persisted timeline events for one subagent."""
    runtime = get_runtime(request)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    payload = await runtime.get_subagent_run_async(session_id, task_id)
    if payload is None:
        return error_response(
            request,
            status_code=404,
            code="SUBAGENT_NOT_FOUND",
            message=f"Subagent '{task_id}' not found in session '{session_id}'",
        )
    events = [
        SubagentEvent.model_validate(item)
        for item in await runtime.list_subagent_events_async(
            session_id,
            task_id,
            after_seq=after_seq,
            limit=limit,
        )
    ]
    return SubagentEventsResponse(
        session_id=session_id,
        task_id=task_id,
        events=events,
    )


@router.get("/sessions/{session_id}/events/stream")
async def stream_session_events(
    request: Request,
    session_id: str,
) -> StreamingResponse:
    """Stream live background session events such as subagent progress."""
    runtime = get_runtime(request)
    summary = await runtime.get_session_summary_async(session_id)
    if summary is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )

    queue = runtime.subscribe_session_events(session_id)

    async def stream() -> Any:
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if item.get("event") == "__close__":
                    return
                yield encode_sse(event=str(item["event"]), data=item)
        finally:
            runtime.unsubscribe_session_events(session_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
    )


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def rename_session(
    request: Request,
    session_id: str,
    payload: SessionRenameRequest,
) -> SessionSummary:
    """Rename one existing session."""
    runtime = get_runtime(request)
    try:
        summary = await runtime.rename_session_async(session_id, payload.title)
    except KeyError:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    return SessionSummary.model_validate(summary)


@router.delete(
    "/sessions/{session_id}",
    response_model=DeleteSessionResponse,
)
async def delete_session(
    request: Request,
    session_id: str,
) -> DeleteSessionResponse:
    """Delete one persisted session."""
    runtime = get_runtime(request)
    await runtime.reset_session_async(session_id)
    return DeleteSessionResponse(session_id=session_id, deleted=True)
