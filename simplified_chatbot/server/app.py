"""FastAPI application factory for picobot."""

from __future__ import annotations

import os
from pathlib import Path
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from simplified_chatbot.config.loader import load_env_for_config, load_config
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.common import error_response, get_request_id
from simplified_chatbot.server.endpoints_capabilities import router as capabilities_router
from simplified_chatbot.server.endpoints_chat import router as chat_router
from simplified_chatbot.server.endpoints_health import router as health_router
from simplified_chatbot.server.endpoints_sessions import router as sessions_router
from simplified_chatbot.server.endpoints_skills import router as skills_router
from simplified_chatbot.server.endpoints_workspace import router as workspace_router
from simplified_chatbot.server.browser.chrome_process import ChromeProcess

try:
    from simplified_chatbot.server.endpoints_screencast import router as screencast_router
except Exception:  # pragma: no cover - optional dependency path
    screencast_router = None


def create_app(
    *,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
    runtime: LocalAgentRuntime | None = None,
    cors_allowed_origins: list[str] | None = None,
) -> FastAPI:
    """Create a FastAPI app backed by the local async runtime."""
    
    config = load_config(config_path) if config_path is not None else None
    chrome = ChromeProcess(
        port=config.browser.get("chromeDebuggingPort") if config and config.browser else None,
        host=config.browser.get("host") if config and config.browser else None,
    )
    
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await chrome.start()
        try:
            yield
        finally:
            chrome.stop()
    
    app = FastAPI(title="picobot", version="0.1.0", lifespan=lifespan)
    resolved_cors_origins = _resolve_cors_allowed_origins(
        config_path=config_path,
        override_origins=cors_allowed_origins,
    )
    if resolved_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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
    app.state.chrome = chrome
    app.state.config = config
    app.include_router(chat_router)
    app.include_router(capabilities_router)
    app.include_router(sessions_router)
    app.include_router(workspace_router)
    app.include_router(skills_router)
    app.include_router(health_router)
    if screencast_router is not None:
        app.include_router(screencast_router)
    return app


def _resolve_cors_allowed_origins(
    *,
    config_path: str | Path | None,
    override_origins: list[str] | None,
) -> list[str]:
    if override_origins is not None:
        return [origin.strip() for origin in override_origins if origin.strip()]
    load_env_for_config(config_path)
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
