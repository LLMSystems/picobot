"""Core types used by the simplified agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypeAlias, TypedDict

Role = Literal["system", "user", "assistant", "tool"]
HistoryRole = Literal["system", "user", "assistant", "tool"]


class ToolFunctionCall(TypedDict):
    """OpenAI-compatible function call payload."""

    name: str
    arguments: str


class ToolCallPayload(TypedDict):
    """OpenAI-compatible tool call payload."""

    id: str
    type: str
    function: ToolFunctionCall


class TextContentBlock(TypedDict):
    """Normalized text content block for multimodal user input."""

    type: Literal["text"]
    text: str


class ImageContentBlock(TypedDict, total=False):
    """Normalized image content block for multimodal user input."""

    type: Literal["image"]
    url: str
    path: str
    mime_type: str
    detail: Literal["auto", "low", "high"]


ContentBlock: TypeAlias = TextContentBlock | ImageContentBlock
MessageContent: TypeAlias = str | list[ContentBlock]


class Message(TypedDict):
    """Minimal chat message structure."""

    role: Role
    content: MessageContent
    tool_calls: NotRequired[list[ToolCallPayload]]
    tool_call_id: NotRequired[str]
    name: NotRequired[str]
    metadata: NotRequired[dict[str, object]]
    id: NotRequired[str]
    created_at: NotRequired[str]


@dataclass(slots=True)
class ToolResult:
    """Envelope a tool returns when it needs to feed images back to the model.

    OpenAI-compatible ``tool`` role messages only accept text, so a tool cannot
    return an image directly. Instead it returns this envelope: ``text`` becomes
    the textual tool result, and ``images`` are injected by the agent loop as a
    follow-up ``user`` message (the only role allowed to carry image blocks).
    """

    text: str
    images: list[ContentBlock] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


@dataclass(slots=True)
class RunResult:
    """Normalized outcome returned by the agent loop."""

    content: str
    messages: list[Message]
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    stop_reason: str = "completed"
