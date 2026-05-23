"""FastAPI capabilities endpoint for picobot frontend bootstrapping."""

from __future__ import annotations

import importlib.util

from fastapi import APIRouter, Request

from simplified_chatbot.server.common import get_runtime
from simplified_chatbot.server.schemas import (
    CapabilitiesFeatures,
    CapabilitiesModelInfo,
    CapabilitiesResponse,
    CapabilitiesToolInfo,
)
from simplified_chatbot.tools.registry import ToolRegistry

router = APIRouter()

_SHELL_TOOLS = frozenset({"exec"})
_FILESYSTEM_TOOLS = frozenset(
    {"read_file", "write_file", "edit_file", "list_dir", "glob", "grep"},
)
_DANGEROUS_TOOLS = frozenset({"exec", "write_file", "edit_file"})


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities(request: Request) -> CapabilitiesResponse:
    """Return frontend-friendly runtime capabilities."""
    runtime = get_runtime(request)
    chatbot = runtime.chatbot
    config = getattr(chatbot, "config", None)
    tools = getattr(chatbot, "tools", None)

    provider_name = str(getattr(config, "provider", "unknown"))
    model_name = str(getattr(config, "model", "unknown"))
    available_models = getattr(config, "available_models", []) if config is not None else []
    max_iterations = int(getattr(config, "max_iterations", 0) or 0)

    return CapabilitiesResponse(
        model=CapabilitiesModelInfo(
            provider=provider_name,
            name=model_name,
        ),
        available_models=[
            item
            for item in (available_models or [model_name])
            if isinstance(item, str) and item
        ],
        max_iterations=max_iterations,
        tools=_build_tool_capabilities(tools),
        features=CapabilitiesFeatures(
            streaming=True,
            session_workspace=runtime.workspace_manager is not None,
            file_upload=(
                runtime.workspace_manager is not None
                and importlib.util.find_spec("multipart") is not None
            ),
            multimodal=True,
            model_override=True,
        ),
    )


def _build_tool_capabilities(tools: object) -> list[CapabilitiesToolInfo]:
    if not isinstance(tools, ToolRegistry):
        return []

    items: list[CapabilitiesToolInfo] = []
    for schema in tools.get_definitions():
        function = schema.get("function")
        if not isinstance(function, dict):
            continue
        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = function.get("description")
        items.append(
            CapabilitiesToolInfo(
                name=name,
                description=description if isinstance(description, str) else "",
                category=_tool_category(name),
                dangerous=name in _DANGEROUS_TOOLS,
            ),
        )
    return items


def _tool_category(name: str) -> str:
    if name in _SHELL_TOOLS:
        return "shell"
    if name in _FILESYSTEM_TOOLS:
        return "filesystem"
    if name.startswith("mcp_"):
        return "mcp"
    return "other"
