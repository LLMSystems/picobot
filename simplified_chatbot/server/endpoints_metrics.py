"""FastAPI endpoints serving the dashboard metrics."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.server.common import error_response
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()

_STREAM_TICK_SECONDS = 10.0

_ALLOWED_RANGES = {"1h", "24h", "7d"}
_ALLOWED_BUCKETS = {"1m", "5m", "15m", "1h", "1d"}


def _get_metrics(request: Request) -> MetricsService:
    svc = getattr(request.app.state, "metrics", None)
    if not isinstance(svc, MetricsService):
        raise RuntimeError("Metrics service is not initialized")
    return svc


@router.get("/metrics/current")
async def metrics_current(request: Request):
    svc = _get_metrics(request)
    return await svc.build_current_snapshot()


@router.get("/metrics/sessions/{session_id}")
async def metrics_session(request: Request, session_id: str):
    svc = _get_metrics(request)
    payload = await svc.build_session_snapshot(session_id)
    if payload is None:
        return error_response(
            request,
            status_code=404,
            code="SESSION_NOT_FOUND",
            message=f"Session '{session_id}' not found",
        )
    return payload


@router.get("/metrics/history")
async def metrics_history(
    request: Request,
    range: str = Query(default="24h"),
    series: str = Query(default=""),
    bucket: str | None = Query(default=None),
):
    if range not in _ALLOWED_RANGES:
        return error_response(
            request,
            status_code=400,
            code="METRICS_RANGE_INVALID",
            message=f"range must be one of {sorted(_ALLOWED_RANGES)}",
        )
    if bucket is not None and bucket not in _ALLOWED_BUCKETS:
        return error_response(
            request,
            status_code=400,
            code="METRICS_BUCKET_INVALID",
            message=f"bucket must be one of {sorted(_ALLOWED_BUCKETS)}",
        )
    metric_names = [s.strip() for s in series.split(",") if s.strip()]
    if not metric_names:
        return error_response(
            request,
            status_code=400,
            code="METRICS_SERIES_REQUIRED",
            message="at least one series name must be provided",
        )

    svc = _get_metrics(request)
    try:
        return await svc.build_history(
            range_token=range,
            series=metric_names,
            bucket_token=bucket,
        )
    except ValueError as exc:
        return error_response(
            request,
            status_code=400,
            code="METRICS_HISTORY_INVALID",
            message=str(exc),
        )


async def stream_metrics_snapshots(
    svc: MetricsService,
    is_disconnected,  # type: ignore[no-untyped-def]
    *,
    tick_seconds: float | None = None,
) -> Any:
    """Yield SSE frames forever, one snapshot per tick.

    Pulled out of the endpoint so tests can drive it directly without paying
    the cost of `httpx.ASGITransport` (which buffers the whole response and
    deadlocks against infinite streams).
    """
    interval = _STREAM_TICK_SECONDS if tick_seconds is None else tick_seconds
    while True:
        if await is_disconnected():
            return
        try:
            snapshot = await svc.build_current_snapshot()
            yield encode_sse(event="metrics_snapshot", data=snapshot)
        except Exception as exc:  # pragma: no cover - defensive
            yield encode_sse(event="error", data={"message": str(exc)})
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return


@router.get("/metrics/stream")
async def metrics_stream(request: Request) -> StreamingResponse:
    """Push the current snapshot every ~10s over SSE.

    Each client gets its own ticker. The first tick fires immediately so the
    UI doesn't sit blank on connect; subsequent ticks fire on a fixed interval.
    """
    svc = _get_metrics(request)
    counter = svc.sse_connections
    counter.enter("metrics")

    async def gen() -> Any:
        try:
            async for frame in stream_metrics_snapshots(svc, request.is_disconnected):
                yield frame
        finally:
            counter.leave("metrics")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
