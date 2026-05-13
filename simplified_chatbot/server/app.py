"""FastAPI application factory for picobot."""

from __future__ import annotations

from pathlib import Path
import uuid

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.common import error_response, get_request_id
from simplified_chatbot.server.endpoints_capabilities import router as capabilities_router
from simplified_chatbot.server.endpoints_chat import router as chat_router
from simplified_chatbot.server.endpoints_health import router as health_router
from simplified_chatbot.server.endpoints_sessions import router as sessions_router


def create_app(
    *,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
    runtime: LocalAgentRuntime | None = None,
) -> FastAPI:
    """Create a FastAPI app backed by the local async runtime."""
    app = FastAPI(title="picobot", version="0.1.0")

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-Id"] = get_request_id(request)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "HTTP_ERROR"
        if exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
        return error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message=str(exc),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message=str(exc),
        )

    if runtime is None:
        resolved_db_path = (
            Path(db_path).expanduser().resolve()
            if db_path is not None
            else (Path.cwd() / "sessions_async.db").resolve()
        )
        store = AioSQLiteSessionStore(resolved_db_path)
        runtime = LocalAgentRuntime.from_config(
            config_path=config_path,
            store=store,
        )

    app.state.runtime = runtime
    app.include_router(chat_router)
    app.include_router(capabilities_router)
    app.include_router(sessions_router)
    app.include_router(health_router)
    return app
