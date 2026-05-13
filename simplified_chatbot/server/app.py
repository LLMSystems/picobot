"""FastAPI application factory for picobot."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
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
    app.include_router(sessions_router)
    app.include_router(health_router)
    return app
