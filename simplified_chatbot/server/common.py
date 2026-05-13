"""Shared FastAPI server helpers."""

from __future__ import annotations

from fastapi import Request

from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime


def get_runtime(request: Request) -> LocalAgentRuntime:
    """Return the application runtime stored on FastAPI app state."""
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, LocalAgentRuntime):
        raise RuntimeError("Application runtime is not initialized")
    return runtime
