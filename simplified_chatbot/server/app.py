"""FastAPI application factory for picobot."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from pathlib import Path
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from simplified_chatbot.config.loader import load_env_for_config, load_config
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server.common import error_response, get_request_id
from simplified_chatbot.auth.users_store import UsersStore
from simplified_chatbot.server.deps import (
    SessionAccessError,
    enforce_session_ownership,
    require_admin,
    require_user,
)
from simplified_chatbot.server.endpoints_auth import router as auth_router
from simplified_chatbot.server.endpoints_capabilities import router as capabilities_router
from simplified_chatbot.server.endpoints_chat import router as chat_router
from simplified_chatbot.server.endpoints_health import router as health_router
from simplified_chatbot.server.endpoints_sessions import router as sessions_router
from simplified_chatbot.server.endpoints_skills import router as skills_router
from simplified_chatbot.server.endpoints_workspace import router as workspace_router
from simplified_chatbot.server.endpoints_metrics import router as metrics_router
from simplified_chatbot.server.endpoints_alerts import router as alerts_router
from simplified_chatbot.server.endpoints_mcp import router as mcp_router
from simplified_chatbot.server.browser.chrome_process import ChromeProcess
from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.metrics.middleware import ApiStatsMiddleware
from simplified_chatbot.metrics.snapshot_store import SnapshotStore
from simplified_chatbot.metrics.snapshot_task import SnapshotTask
from simplified_chatbot.metrics.chat_usage_store import ChatUsageStore
from simplified_chatbot.metrics.llm_call_store import LlmCallStore
from simplified_chatbot.alerts.events_store import AlertEventsStore
from simplified_chatbot.alerts.rules import load_rules
from simplified_chatbot.alerts.service import AlertService

try:
    from simplified_chatbot.server.endpoints_screencast import router as screencast_router
except Exception:  # pragma: no cover - optional dependency path
    screencast_router = None


logger = logging.getLogger("picobot.server.app")


def create_app(
    *,
    config_path: str | Path | None = None,
    db_path: str | Path | None = None,
    runtime: LocalAgentRuntime | None = None,
    cors_allowed_origins: list[str] | None = None,
    alerts_config_path: str | Path | None = None,
) -> FastAPI:
    """Create a FastAPI app backed by the local async runtime."""
    
    config = load_config(config_path) if config_path is not None else None
    chrome = ChromeProcess(
        port=config.browser.get("chromeDebuggingPort") if config and config.browser else None,
        host=config.browser.get("host") if config and config.browser else None,
    )
    
    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        mcp_connect_task: asyncio.Task[None] | None = None
        if chrome is not None:
            await chrome.start()
        runtime_ = getattr(app_.state, "runtime", None)
        ensure_mcp_connected = getattr(runtime_, "ensure_mcp_connected_async", None)
        if callable(ensure_mcp_connected):
            async def _connect_mcp_in_background() -> None:
                try:
                    await ensure_mcp_connected()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("background MCP startup failed")

            mcp_connect_task = asyncio.create_task(_connect_mcp_in_background())
            app_.state.mcp_connect_task = mcp_connect_task
        # Re-hydrate alert firing state from DB before the snapshot task starts
        # evaluating; otherwise a fresh server would re-fire all active alerts.
        alerts = getattr(app_.state, "alerts", None)
        if alerts is not None:
            try:
                await alerts.hydrate_from_db()
            except Exception:
                pass
        snapshot_task = getattr(app_.state, "snapshot_task", None)
        if snapshot_task is not None:
            await snapshot_task.start()
        try:
            yield
        finally:
            if snapshot_task is not None:
                await snapshot_task.stop()
            if mcp_connect_task is not None and not mcp_connect_task.done():
                mcp_connect_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await mcp_connect_task
            close_mcp = getattr(runtime_, "close_mcp_async", None)
            if callable(close_mcp):
                await close_mcp()
            if chrome is not None:
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

    # Signed httpOnly session cookie. Carries only {"user_id": int}; chosen over
    # Bearer tokens so the frontend's EventSource streams (which cannot set
    # Authorization headers) authenticate via cookie with withCredentials.
    session_secret, session_https_only = _resolve_session_settings(config_path)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="picobot_session",
        same_site="lax",
        https_only=session_https_only,
    )

    # Raw ASGI middleware — pure asgi (not BaseHTTPMiddleware) so streaming
    # responses (e.g. SSE on /metrics/stream and /chat/stream) pass through
    # without being buffered.
    class _RequestIdMiddleware:
        def __init__(self, inner):  # type: ignore[no-untyped-def]
            self._inner = inner

        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            if scope.get("type") != "http":
                await self._inner(scope, receive, send)
                return
            request_id = f"req_{uuid.uuid4().hex}"
            state = scope.setdefault("state", {})
            state["request_id"] = request_id
            header_value = request_id.encode("latin-1")

            async def send_with_header(message):  # type: ignore[no-untyped-def]
                if message.get("type") == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"x-request-id", header_value))
                    message = {**message, "headers": headers}
                await send(message)

            await self._inner(scope, receive, send_with_header)

    app.add_middleware(_RequestIdMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "HTTP_ERROR"
        if exc.status_code == 401:
            code = "UNAUTHENTICATED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 405:
            code = "METHOD_NOT_ALLOWED"
        return error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )

    @app.exception_handler(SessionAccessError)
    async def handle_session_access_error(request: Request, exc: SessionAccessError) -> JSONResponse:
        # Rendered identically to a missing session so ownership can't be probed.
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{exc.session_id}' not found",
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

    # Users live in the same SQLite file as sessions so a single DB path backs
    # the whole app; fall back to the conventional path when the runtime store
    # does not expose one (e.g. in-memory test doubles).
    users_db_path = getattr(getattr(runtime, "store", None), "db_path", None)
    if users_db_path is None:
        users_db_path = (Path.cwd() / "sessions_async.db").resolve()
    app.state.users_store = UsersStore(users_db_path)

    metrics = _build_metrics_service(runtime, chrome)
    app.state.metrics = metrics
    app.add_middleware(ApiStatsMiddleware, recorder=metrics.api_stats)

    alert_service = _build_alert_service(
        metrics_db_path=getattr(metrics, "_db_path", None),
        alerts_config_path=alerts_config_path,
    )
    app.state.alerts = alert_service

    if metrics.snapshot_store is not None:
        snapshot_db_path = getattr(metrics, "_db_path", None)
        app.state.snapshot_task = SnapshotTask(
            service=metrics,
            store=metrics.snapshot_store,
            db_path=str(snapshot_db_path) if snapshot_db_path else None,
            # 10s — drives both snapshot persistence AND alert evaluation,
            # so alerts fire within ~10s of their condition becoming true.
            interval_seconds=10,
            alert_service=alert_service,
        )

    # Protected routes (need a logged-in user) vs public routes.
    # capabilities/health/metrics/alerts stay public: the frontend reads them
    # before login, and metrics/alerts is operational telemetry.
    protected = [Depends(require_user)]
    # Session-scoped routers additionally enforce per-session ownership on any
    # /sessions/{session_id}/... route (no-op on collection / body-scoped routes).
    session_scoped = [Depends(require_user), Depends(enforce_session_ownership)]
    # The operational dashboard is system-wide / cross-user, so it is admin-only.
    admin_only = [Depends(require_admin)]
    app.include_router(auth_router)
    app.include_router(capabilities_router)
    app.include_router(health_router)
    app.include_router(metrics_router, dependencies=admin_only)
    app.include_router(alerts_router, dependencies=admin_only)
    app.include_router(chat_router, dependencies=session_scoped)
    app.include_router(sessions_router, dependencies=session_scoped)
    app.include_router(workspace_router, dependencies=session_scoped)
    app.include_router(skills_router, dependencies=protected)
    app.include_router(mcp_router, dependencies=protected)
    if screencast_router is not None:
        app.include_router(screencast_router, dependencies=session_scoped)
    return app


def _build_alert_service(
    *,
    metrics_db_path: Path | None,
    alerts_config_path: str | Path | None,
) -> AlertService | None:
    """Load alert rules from YAML and wire an AlertService.

    Returns None if no rules path was given or the config file is empty —
    the rest of the dashboard keeps working without an alerts layer.
    """
    if metrics_db_path is None:
        return None
    # Default to alerts.yaml sitting next to the working directory.
    rules_path = (
        Path(alerts_config_path).expanduser().resolve()
        if alerts_config_path is not None
        else (Path.cwd() / "alerts.yaml")
    )
    rules = load_rules(rules_path) if rules_path.exists() else []
    if not rules:
        return None
    store = AlertEventsStore(metrics_db_path)
    return AlertService(store=store, rules=rules)


def _build_metrics_service(
    runtime: LocalAgentRuntime,
    chrome: ChromeProcess,
) -> MetricsService:
    """Wire the MetricsService against the active runtime/store."""
    db_path = None
    store = getattr(runtime, "store", None)
    if store is not None and hasattr(store, "db_path"):
        db_path = getattr(store, "db_path")
    workspace_root = None
    if runtime.workspace_manager is not None:
        workspace_root = getattr(runtime.workspace_manager, "root_dir", None) or getattr(
            runtime.workspace_manager, "workspace_root", None,
        )
    snapshot_store = SnapshotStore(db_path) if db_path is not None else None
    chat_usage_store = ChatUsageStore(db_path) if db_path is not None else None
    llm_call_store = LlmCallStore(db_path) if db_path is not None else None
    service = MetricsService(
        db_path=db_path,
        workspace_root_dir=workspace_root,
        snapshot_store=snapshot_store,
        chat_usage_store=chat_usage_store,
        llm_call_store=llm_call_store,
    )
    service.set_chrome_status_provider(
        lambda: chrome.proc is not None and chrome.proc.poll() is None,
    )
    return service


def _resolve_session_settings(config_path: str | Path | None) -> tuple[str, bool]:
    """Resolve the session-cookie secret and secure flag from the environment.

    ``SESSION_SECRET`` signs the cookie. Missing it is fine for local dev — we
    generate an ephemeral secret (so cookies reset on restart) and warn — but a
    real deployment must set a stable value or every restart logs everyone out.
    ``SESSION_COOKIE_SECURE`` should be ``true`` behind HTTPS.
    """
    load_env_for_config(config_path)
    secret = os.environ.get("SESSION_SECRET", "").strip()
    if not secret:
        logger.warning(
            "SESSION_SECRET is not set; generating an ephemeral secret. "
            "Sessions will be invalidated on restart. Set SESSION_SECRET in production.",
        )
        secret = uuid.uuid4().hex + uuid.uuid4().hex
    https_only = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return secret, https_only


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
