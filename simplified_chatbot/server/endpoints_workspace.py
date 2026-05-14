"""FastAPI workspace browsing endpoints for picobot."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import WorkspaceFileResponse, WorkspaceTreeResponse

router = APIRouter()


@router.get(
    "/sessions/{session_id}/workspace/tree",
    response_model=WorkspaceTreeResponse,
)
async def get_workspace_tree(
    request: Request,
    session_id: str,
    path: str = Query(default="."),
    recursive: bool = Query(default=False),
    max_entries: int = Query(default=200, ge=1),
) -> WorkspaceTreeResponse:
    """List one directory in the session workspace."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.list_workspace_tree_async(
            session_id,
            path=path,
            recursive=recursive,
            max_entries=max_entries,
        )
    except KeyError:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="WORKSPACE_NOT_AVAILABLE",
            message=str(exc),
        )
    except ValueError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_PATH_INVALID",
            message=str(exc),
        )
    except FileNotFoundError:
        return error_response(
            request,
            status_code=404,
            code="WORKSPACE_DIRECTORY_NOT_FOUND",
            message=f"Directory '{path}' not found",
        )
    except NotADirectoryError:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_NOT_A_DIRECTORY",
            message=f"Path '{path}' is not a directory",
        )
    return WorkspaceTreeResponse.model_validate(payload)


@router.get(
    "/sessions/{session_id}/workspace/file",
    response_model=WorkspaceFileResponse,
)
async def get_workspace_file(
    request: Request,
    session_id: str,
    path: str = Query(min_length=1),
    offset: int = Query(default=1, ge=1),
    limit: int = Query(default=2000, ge=1),
) -> WorkspaceFileResponse:
    """Read one UTF-8 text file from the session workspace."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.read_workspace_file_async(
            session_id,
            path=path,
            offset=offset,
            limit=limit,
        )
    except KeyError:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    except RuntimeError as exc:
        return error_response(
            request,
            status_code=409,
            code="WORKSPACE_NOT_AVAILABLE",
            message=str(exc),
        )
    except ValueError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_PATH_INVALID",
            message=str(exc),
        )
    except FileNotFoundError:
        return error_response(
            request,
            status_code=404,
            code="WORKSPACE_FILE_NOT_FOUND",
            message=f"File '{path}' not found",
        )
    except IsADirectoryError:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_NOT_A_FILE",
            message=f"Path '{path}' is not a file",
        )
    except UnicodeDecodeError:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_BINARY_FILE_UNSUPPORTED",
            message=f"File '{path}' is not a UTF-8 text file",
        )
    return WorkspaceFileResponse.model_validate(payload)
