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
from simplified_chatbot.server.endpoints_metrics import router as metrics_router
from simplified_chatbot.server.endpoints_alerts import router as alerts_router
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
        await chrome.start()
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

    app.include_router(chat_router)
    app.include_router(capabilities_router)
    app.include_router(sessions_router)
    app.include_router(workspace_router)
    app.include_router(skills_router)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(alerts_router)
    if screencast_router is not None:
        app.include_router(screencast_router)
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
