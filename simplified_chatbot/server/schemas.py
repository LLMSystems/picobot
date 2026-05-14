"""Pydantic schemas for FastAPI chat endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Structured error payload."""

    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    error: ErrorDetail


class ChatTraceEvent(BaseModel):
    """One collected agent event for non-stream chat responses."""

    event: str
    data: dict[str, object] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """Request body for one chat turn."""

    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ChatStreamRequest(ChatRequest):
    """Request body for one streamed chat turn."""

    client_request_id: str | None = Field(default=None, min_length=1)


class ChatResponse(BaseModel):
    """Response body for one completed chat turn."""

    session_id: str
    content: str
    usage: dict[str, int] = Field(default_factory=dict)
    tools_used: list[str] = Field(default_factory=list)
    stop_reason: str = "stop"
    events: list[ChatTraceEvent] = Field(default_factory=list)


class ChatStreamDone(BaseModel):
    """Final SSE payload for one completed streamed turn."""

    session_id: str
    content: str
    usage: dict[str, int] = Field(default_factory=dict)
    tools_used: list[str] = Field(default_factory=list)
    stop_reason: str = "stop"


class SessionSummary(BaseModel):
    """Frontend-friendly metadata for one session."""

    session_id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0
    last_user_message: str = ""
    last_assistant_preview: str = ""


class SessionCreateRequest(BaseModel):
    """Request body for creating one session."""

    title: str | None = None
    session_id: str | None = Field(default=None, min_length=1)


class SessionRenameRequest(BaseModel):
    """Request body for renaming one session."""

    title: str = Field(min_length=1)


class SessionListResponse(BaseModel):
    """Response body for listing session ids."""

    sessions: list[SessionSummary] = Field(default_factory=list)


class SessionMessagesResponse(BaseModel):
    """Response body for one session's stored messages."""

    session_id: str
    messages: list[dict[str, object]] = Field(default_factory=list)


class DeleteSessionResponse(BaseModel):
    """Response body for deleting one session."""

    session_id: str
    deleted: bool = True


class CapabilitiesModelInfo(BaseModel):
    """Frontend-facing model/provider metadata."""

    provider: str
    name: str


class CapabilitiesToolInfo(BaseModel):
    """Frontend-facing tool metadata."""

    name: str
    description: str
    category: str
    dangerous: bool = False


class CapabilitiesFeatures(BaseModel):
    """Feature flags exposed to the frontend."""

    streaming: bool = True
    session_workspace: bool = False
    file_upload: bool = False
    multimodal: bool = False


class CapabilitiesResponse(BaseModel):
    """Capabilities summary for frontend UI bootstrapping."""

    model: CapabilitiesModelInfo
    max_iterations: int
    tools: list[CapabilitiesToolInfo] = Field(default_factory=list)
    features: CapabilitiesFeatures


class WorkspaceTreeEntry(BaseModel):
    """One workspace tree entry."""

    path: str
    name: str
    type: str
    size: int | None = None
    updated_at: str | None = None


class WorkspaceTreeResponse(BaseModel):
    """Response body for listing one workspace directory."""

    session_id: str
    path: str
    entries: list[WorkspaceTreeEntry] = Field(default_factory=list)
    truncated: bool = False


class WorkspaceFileResponse(BaseModel):
    """Response body for reading one workspace file."""

    session_id: str
    path: str
    content: str
    encoding: str = "utf-8"
    truncated: bool = False
    line_count: int = 0


class HealthResponse(BaseModel):
    """Simple health check payload."""

    status: str
