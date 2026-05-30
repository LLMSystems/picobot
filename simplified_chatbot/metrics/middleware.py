"""Raw ASGI middleware feeding the ApiStatsRecorder.

Records (endpoint_template, status_code, duration_ms) for every HTTP request,
except `/metrics/*` paths (to avoid feedback noise from dashboard polling).

We intentionally do NOT use `BaseHTTPMiddleware`: that base class buffers
streaming responses, which would deadlock SSE endpoints.
"""

from __future__ import annotations

from time import perf_counter
from typing import Any, Awaitable, Callable

from simplified_chatbot.metrics.recorders import ApiStatsRecorder

_EXCLUDED_PREFIXES = ("/metrics",)


class ApiStatsMiddleware:
    """Pure ASGI middleware so StreamingResponse bodies pass through unchanged."""

    def __init__(self, app, recorder: ApiStatsRecorder) -> None:
        self.app = app
        self._recorder = recorder

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = perf_counter()
        status_holder: dict[str, int] = {"code": 500}

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                status_holder["code"] = int(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (perf_counter() - start) * 1000.0
            endpoint = _endpoint_template(scope)
            self._recorder.record(
                endpoint=endpoint,
                status_code=status_holder["code"],
                duration_ms=duration_ms,
            )


def _endpoint_template(scope: dict[str, Any]) -> str:
    """Prefer the route template (`/sessions/{session_id}`) over the raw URL.

    Falling back to the raw path means we'd explode cardinality on
    user-id-style segments. When no route matched (404), we group everything
    under a single bucket.
    """
    route = scope.get("route")
    if route is not None:
        path = getattr(route, "path", None)
        if isinstance(path, str) and path:
            return path
    return "__unmatched__"
