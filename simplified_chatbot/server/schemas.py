"""Pydantic schemas for FastAPI chat endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class ChatImageInput(BaseModel):
    """One optional image attachment for a chat turn."""

    path: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    detail: str = Field(default="auto")

    @model_validator(mode="after")
    def _validate_source(self) -> "ChatImageInput":
        if bool(self.path) == bool(self.url):
            raise ValueError("Exactly one of path or url must be provided")
        if self.detail not in {"auto", "low", "high"}:
            raise ValueError("detail must be one of auto, low, or high")
        return self


class ChatRequest(BaseModel):
    """Request body for one chat turn."""

    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    model: str | None = Field(default=None, min_length=1)
    subagent_model: str | None = Field(default=None, min_length=1)
    images: list[ChatImageInput] = Field(default_factory=list)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_iterations: int | None = Field(default=None, gt=0)
    system_prompt: str | None = Field(default=None)
    disabled_tools: list[str] = Field(default_factory=list)


class ChatStreamRequest(ChatRequest):
    """Request body for one streamed chat turn."""

    client_request_id: str | None = Field(default=None, min_length=1)
    include_trace: bool = True


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


class SessionMemoryNote(BaseModel):
    """One user-managed note attached to a session memory."""

    id: int
    session_id: str
    kind: Literal["note", "preference", "correction"] = "note"
    content: str
    created_at: str
    updated_at: str


class SessionMemoryNoteCreateRequest(BaseModel):
    """Request body for creating one user memory note."""

    content: str = Field(min_length=1, max_length=2000)
    kind: Literal["note", "preference", "correction"] = "note"


class SessionMemoryResponse(BaseModel):
    """Response body for one session's rolling memory summary."""

    session_id: str
    enabled: bool
    has_summary: bool = False
    summary: str = ""
    compacted_message_count: int = 0
    updated_at: str | None = None
    notes: list[SessionMemoryNote] = Field(default_factory=list)


class SessionMemoryNoteDeleteResponse(BaseModel):
    """Response body for archiving one user memory note."""

    session_id: str
    note_id: int
    deleted: bool = True


class SubagentRun(BaseModel):
    """Persisted summary for one subagent task."""

    task_id: str
    parent_session_id: str
    label: str
    task: str
    workspace: str | None = None
    phase: str
    started_at: str
    finished_at: str | None = None
    stop_reason: str | None = None
    ok: bool | None = None
    error: str | None = None
    usage: dict[str, object] = Field(default_factory=dict)
    tool_events: list[dict[str, object]] = Field(default_factory=list)
    final_content: str | None = None
    model: str | None = None


class SubagentRunListResponse(BaseModel):
    """Response body for listing persisted subagent runs in one session."""

    session_id: str
    items: list[SubagentRun] = Field(default_factory=list)


class SubagentEvent(BaseModel):
    """Persisted timeline event for one subagent."""

    id: int
    task_id: str
    parent_session_id: str
    seq: int
    event_type: str
    created_at: str
    payload: dict[str, object] = Field(default_factory=dict)


class SubagentEventsResponse(BaseModel):
    """Response body for listing persisted events for one subagent."""

    session_id: str
    task_id: str
    events: list[SubagentEvent] = Field(default_factory=list)


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
    display_name: str | None = None
    description_zh: str | None = None


class CapabilitiesFeatures(BaseModel):
    """Feature flags exposed to the frontend."""

    streaming: bool = True
    session_workspace: bool = False
    file_upload: bool = False
    multimodal: bool = False
    model_override: bool = False


class CapabilitiesResponse(BaseModel):
    """Capabilities summary for frontend UI bootstrapping."""

    model: CapabilitiesModelInfo
    available_models: list[str] = Field(default_factory=list)
    default_subagent_model: str | None = None
    max_iterations: int
    tools: list[CapabilitiesToolInfo] = Field(default_factory=list)
    features: CapabilitiesFeatures
    default_system_prompt: str = ""
    default_temperature: float = 0.7
    default_max_tokens: int | None = None


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


class WorkspaceUploadedFile(BaseModel):
    """Metadata for one successfully uploaded workspace file."""

    path: str
    name: str
    size: int
    content_type: str | None = None
    overwritten: bool = False


class WorkspaceSkippedFile(BaseModel):
    """Metadata for one skipped upload item."""

    name: str
    reason: str


class WorkspaceUploadResponse(BaseModel):
    """Response body for uploading one or more workspace files."""

    session_id: str
    path: str
    uploaded: list[WorkspaceUploadedFile] = Field(default_factory=list)
    skipped: list[WorkspaceSkippedFile] = Field(default_factory=list)


class WorkspaceDeleteResponse(BaseModel):
    """Response body for deleting one workspace file."""

    session_id: str
    path: str
    deleted: bool = True


class WorkspaceMkdirRequest(BaseModel):
    """Request body for creating one workspace directory."""

    path: str = Field(min_length=1)


class WorkspaceMkdirResponse(BaseModel):
    """Response body for creating one workspace directory."""

    session_id: str
    path: str
    created: bool = True


class WorkspaceMoveRequest(BaseModel):
    """Request body for moving one workspace file or directory."""

    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)
    overwrite: bool = False


class WorkspaceMoveResponse(BaseModel):
    """Response body for moving one workspace file or directory."""

    session_id: str
    src: str
    dst: str
    type: str
    overwritten: bool = False


class WorkspaceSaveFileRequest(BaseModel):
    """Request body for saving (overwriting) one workspace file."""

    path: str = Field(min_length=1)
    content: str


class WorkspaceSaveFileResponse(BaseModel):
    """Response body for saving one workspace file."""

    session_id: str
    path: str
    saved: bool = True
    size: int = 0
    updated_at: str = ""


class WorkspaceCreateFileRequest(BaseModel):
    """Request body for creating one workspace file."""

    path: str = Field(min_length=1)
    content: str = ""
    overwrite: bool = False


class WorkspaceCreateFileResponse(BaseModel):
    """Response body for creating one workspace file."""

    session_id: str
    path: str
    created: bool = True


class WorkspaceDeleteDirectoryResponse(BaseModel):
    """Response body for deleting one workspace directory."""

    session_id: str
    path: str
    deleted: bool = True


class SkillInfo(BaseModel):
    """One skill entry in the global skill library."""

    name: str
    source: str  # "builtin" | "custom"
    description: str = ""
    always: bool = False
    disabled: bool = False


class SkillListResponse(BaseModel):
    """Response body for listing all skills."""

    skills: list[SkillInfo]


class SkillUploadFile(BaseModel):
    """One optional supplementary file shipped with a custom skill."""

    path: str = Field(min_length=1)
    content_base64: str


class SkillCreateRequest(BaseModel):
    """Request body for creating or overwriting a custom skill."""

    name: str = Field(min_length=1)
    content: str = Field(min_length=1)
    files: list[SkillUploadFile] = Field(default_factory=list)


class SkillMutationResponse(BaseModel):
    """Response body for create / delete / toggle operations."""

    name: str
    ok: bool = True


class SkillDisableRequest(BaseModel):
    """Request body for enabling / disabling a skill."""

    disabled: bool


class HealthResponse(BaseModel):
    """Simple health check payload."""

    status: str


class McpServerStatus(BaseModel):
    """Diagnostics for one configured MCP server."""

    name: str
    transport: str
    connected: bool = False
    connecting: bool = False
    tool_count: int = 0
    tool_names: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    include_resources: bool = False
    include_prompts: bool = False
    error: str | None = None


class McpStatusResponse(BaseModel):
    """Runtime MCP status and diagnostics."""

    supported: bool = False
    reload_supported: bool = False
    enabled: bool = False
    configured_server_count: int = 0
    connected_server_count: int = 0
    connecting_server_count: int = 0
    tool_count: int = 0
    servers: list[McpServerStatus] = Field(default_factory=list)


class McpReloadResponse(McpStatusResponse):
    """Response body for MCP hot reload."""

    ok: bool = True
    message: str = ""
    added: list[str] = Field(default_factory=list)
    changed: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    connected: list[str] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)


class AskUserQuestionAnswerRequest(BaseModel):
    """Request body for submitting user answers to a pending ask_user_question call."""

    answers: dict[str, object] = Field(
        description=(
            "Map of question text → selected option label(s). "
            "Single-select: string value. Multi-select: list of strings."
        ),
    )


class AskUserQuestionAnswerResponse(BaseModel):
    """Response body for submitting user answers."""

    ok: bool
