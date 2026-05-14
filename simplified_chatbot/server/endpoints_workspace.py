"""FastAPI workspace browsing endpoints for picobot."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from simplified_chatbot.server.common import error_response, get_runtime
from simplified_chatbot.server.schemas import (
    WorkspaceDeleteResponse,
    WorkspaceFileResponse,
    WorkspaceMkdirRequest,
    WorkspaceMkdirResponse,
    WorkspaceMoveRequest,
    WorkspaceMoveResponse,
    WorkspaceTreeResponse,
    WorkspaceUploadResponse,
)
from simplified_chatbot.runtime.local_runtime import (
    UploadFileInput,
    WorkspaceFilenameInvalidError,
    WorkspaceMoveDestinationExistsError,
    WorkspaceMoveDestinationIsDirectoryError,
    WorkspaceMoveDestinationParentMissingError,
    WorkspaceMoveIntoSelfError,
    WorkspaceMoveRootForbiddenError,
    WorkspaceMoveSamePathError,
    WorkspaceUploadFileTooLargeError,
    WorkspaceUploadNoFilesError,
    WorkspaceUploadTooManyFilesError,
)

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


@router.post(
    "/sessions/{session_id}/workspace/upload",
    response_model=WorkspaceUploadResponse,
)
async def upload_workspace_files(
    request: Request,
    session_id: str,
    path: str = Query(default="."),
    overwrite: bool = Query(default=False),
) -> WorkspaceUploadResponse:
    """Upload one or more files into the session workspace."""
    runtime = get_runtime(request)
    form = await request.form()
    files = [item for _, item in form.multi_items() if hasattr(item, "read")]
    if not files:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_UPLOAD_NO_FILES",
            message="No files were provided",
        )

    payload_files = [
        UploadFileInput(
            name=str(getattr(item, "filename", "") or ""),
            content=await item.read(),
            content_type=getattr(item, "content_type", None),
        )
        for item in files
    ]
    try:
        payload = await runtime.upload_workspace_files_async(
            session_id,
            path=path,
            files=payload_files,
            overwrite=overwrite,
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
    except WorkspaceUploadNoFilesError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_UPLOAD_NO_FILES",
            message=str(exc),
        )
    except WorkspaceFilenameInvalidError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_UPLOAD_FILENAME_INVALID",
            message=str(exc),
        )
    except WorkspaceUploadFileTooLargeError as exc:
        return error_response(
            request,
            status_code=413,
            code="WORKSPACE_UPLOAD_FILE_TOO_LARGE",
            message=str(exc),
        )
    except WorkspaceUploadTooManyFilesError as exc:
        return error_response(
            request,
            status_code=413,
            code="WORKSPACE_UPLOAD_TOO_MANY_FILES",
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
    return WorkspaceUploadResponse.model_validate(payload)


@router.delete(
    "/sessions/{session_id}/workspace/file",
    response_model=WorkspaceDeleteResponse,
)
async def delete_workspace_file(
    request: Request,
    session_id: str,
    path: str = Query(min_length=1),
) -> WorkspaceDeleteResponse:
    """Delete one file from the session workspace."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.delete_workspace_file_async(
            session_id,
            path=path,
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
    return WorkspaceDeleteResponse.model_validate(payload)


@router.post(
    "/sessions/{session_id}/workspace/mkdir",
    response_model=WorkspaceMkdirResponse,
)
async def create_workspace_directory(
    request: Request,
    session_id: str,
    body: WorkspaceMkdirRequest,
) -> WorkspaceMkdirResponse:
    """Create one directory inside the session workspace."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.create_workspace_directory_async(
            session_id,
            path=body.path,
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
    except NotADirectoryError:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_NOT_A_DIRECTORY",
            message=f"Path '{body.path}' is not a directory",
        )
    return WorkspaceMkdirResponse.model_validate(payload)


@router.post(
    "/sessions/{session_id}/workspace/move",
    response_model=WorkspaceMoveResponse,
)
async def move_workspace_entry(
    request: Request,
    session_id: str,
    body: WorkspaceMoveRequest,
) -> WorkspaceMoveResponse:
    """Move or rename one file or directory inside the session workspace."""
    runtime = get_runtime(request)
    try:
        payload = await runtime.move_workspace_entry_async(
            session_id,
            src=body.src,
            dst=body.dst,
            overwrite=body.overwrite,
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
    except WorkspaceMoveRootForbiddenError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_MOVE_ROOT_FORBIDDEN",
            message=str(exc),
        )
    except WorkspaceMoveSamePathError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_MOVE_SAME_PATH",
            message=str(exc),
        )
    except WorkspaceMoveIntoSelfError as exc:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_MOVE_INTO_SELF",
            message=str(exc),
        )
    except WorkspaceMoveDestinationExistsError as exc:
        return error_response(
            request,
            status_code=409,
            code="WORKSPACE_MOVE_DESTINATION_EXISTS",
            message=str(exc),
        )
    except WorkspaceMoveDestinationIsDirectoryError as exc:
        return error_response(
            request,
            status_code=409,
            code="WORKSPACE_MOVE_DESTINATION_IS_DIRECTORY",
            message=str(exc),
        )
    except WorkspaceMoveDestinationParentMissingError:
        return error_response(
            request,
            status_code=404,
            code="WORKSPACE_DIRECTORY_NOT_FOUND",
            message=f"Destination parent directory for '{body.dst}' not found",
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
            message=f"File '{body.src}' not found",
        )
    except NotADirectoryError:
        return error_response(
            request,
            status_code=400,
            code="WORKSPACE_NOT_A_DIRECTORY",
            message=f"Destination parent for '{body.dst}' is not a directory",
        )
    return WorkspaceMoveResponse.model_validate(payload)
