"""Core types used by the simplified agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypeAlias, TypedDict

Role = Literal["system", "user", "assistant", "tool"]
HistoryRole = Literal["user", "assistant", "tool"]


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
