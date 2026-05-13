"""FastAPI session and history endpoints for picobot."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from simplified_chatbot.server.common import get_runtime
from simplified_chatbot.server.schemas import (
    DeleteSessionResponse,
    SessionListResponse,
    SessionMessagesResponse,
)

router = APIRouter()


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request) -> SessionListResponse:
    """List known session ids."""
    runtime = get_runtime(request)
    sessions = await runtime.list_sessions_async()
    return SessionListResponse(sessions=sessions)


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
    if not messages:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    return SessionMessagesResponse(session_id=session_id, messages=messages)


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
