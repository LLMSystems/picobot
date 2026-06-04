"""FastAPI endpoints for MCP diagnostics and hot reload."""

from __future__ import annotations

from fastapi import APIRouter, Request

from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import McpReloadResponse, McpStatusResponse

router = APIRouter()


@router.get("/mcp/status", response_model=McpStatusResponse)
async def get_mcp_status(request: Request) -> McpStatusResponse:
    """Return runtime MCP connection diagnostics."""
    runtime = get_runtime(request)
    return McpStatusResponse.model_validate(runtime.get_mcp_status())


@router.post("/mcp/reload", response_model=McpReloadResponse)
async def reload_mcp(request: Request):
    """Reload MCP config from disk and reconcile live connections."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.reload_mcp_async()
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=400,
            code="MCP_RELOAD_UNAVAILABLE",
            message=str(exc),
        )
    except Exception as exc:
        return error_response(
            request,
            status_code=500,
            code="MCP_RELOAD_FAILED",
            message=str(exc),
        )
    return McpReloadResponse.model_validate(payload)
