"""Agent type definitions and registry for multi-agent support."""

from __future__ import annotations

from simplified_chatbot.agents.registry import (
    AgentDefinition,
    AgentRegistry,
    KNOWN_TOOL_NAMES,
)

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
    "KNOWN_TOOL_NAMES",
]
