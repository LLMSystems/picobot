"""FastAPI endpoints for MCP diagnostics and hot reload."""

from __future__ import annotations

from fastapi import APIRouter, Request

from simplified_chatbot.config.schema import MCPServerConfig
from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import (
    McpReloadResponse,
    McpServersConfigResponse,
    McpStatusResponse,
)

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


@router.get("/mcp/servers", response_model=McpServersConfigResponse)
async def get_mcp_servers(request: Request):
    """Return the on-disk MCP server configs (with ${ENV} placeholders intact)."""
    runtime = get_runtime(request)
    try:
        servers = runtime.get_mcp_raw_servers()
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=400,
            code="MCP_EDIT_UNAVAILABLE",
            message=str(exc),
        )
    return McpServersConfigResponse(servers=servers)


@router.put("/mcp/servers/{name}", response_model=McpReloadResponse)
async def upsert_mcp_server(request: Request, name: str, body: MCPServerConfig):
    """Create or replace one MCP server in config.json and reconcile connections."""
    runtime = get_runtime(request)
    raw_server = body.model_dump(mode="json", by_alias=True)
    try:
        payload = await runtime.upsert_mcp_server_async(name, raw_server)
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=400,
            code="MCP_EDIT_UNAVAILABLE",
            message=str(exc),
        )
    except ValueError as exc:
        return error_response(
            request,
            status_code=400,
            code="MCP_SERVER_INVALID",
            message=str(exc),
        )
    except Exception as exc:
        return error_response(
            request,
            status_code=500,
            code="MCP_EDIT_FAILED",
            message=str(exc),
        )
    return McpReloadResponse.model_validate(payload)


@router.delete("/mcp/servers/{name}", response_model=McpReloadResponse)
async def delete_mcp_server(request: Request, name: str):
    """Remove one MCP server from config.json and reconcile connections."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.remove_mcp_server_async(name)
    except KeyError:
        return error_response(
            request,
            status_code=404,
            code="MCP_SERVER_NOT_FOUND",
            message=f"MCP server '{name}' not found",
        )
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=400,
            code="MCP_EDIT_UNAVAILABLE",
            message=str(exc),
        )
    except Exception as exc:
        return error_response(
            request,
            status_code=500,
            code="MCP_EDIT_FAILED",
            message=str(exc),
        )
    return McpReloadResponse.model_validate(payload)
