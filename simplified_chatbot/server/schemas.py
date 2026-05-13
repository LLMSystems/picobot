"""Pydantic schemas for FastAPI chat endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request body for one chat turn."""

    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """Response body for one completed chat turn."""

    session_id: str
    content: str
    usage: dict[str, int] = Field(default_factory=dict)
    tools_used: list[str] = Field(default_factory=list)
    stop_reason: str = "stop"


class ChatStreamDone(ChatResponse):
    """Final SSE payload for one completed streamed turn."""


class ErrorResponse(BaseModel):
    """Simple error payload for API responses."""

    error: str


class SessionListResponse(BaseModel):
    """Response body for listing session ids."""

    sessions: list[str] = Field(default_factory=list)


class SessionMessagesResponse(BaseModel):
    """Response body for one session's stored messages."""

    session_id: str
    messages: list[dict[str, object]] = Field(default_factory=list)


class DeleteSessionResponse(BaseModel):
    """Response body for deleting one session."""

    session_id: str
    deleted: bool = True


class HealthResponse(BaseModel):
    """Simple health check payload."""

    status: str
