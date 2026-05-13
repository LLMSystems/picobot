"""FastAPI session and history endpoints for picobot."""

from __future__ import annotations

from fastapi import APIRouter, Request

from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import (
    DeleteSessionResponse,
    SessionCreateRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionRenameRequest,
    SessionSummary,
)

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
