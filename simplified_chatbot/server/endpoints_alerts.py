"""FastAPI endpoints for the alerts layer."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from simplified_chatbot.alerts.events_store import AlertEventRow
from simplified_chatbot.alerts.service import AlertService
from simplified_chatbot.server.common import error_response
from simplified_chatbot.server.sse import encode_sse

router = APIRouter()


def _get_alerts(request: Request) -> AlertService | None:
    return getattr(request.app.state, "alerts", None)


def _row_dict(row: AlertEventRow, svc: AlertService | None = None) -> dict:
    """Serialize one alert event. When `svc` is supplied, the result is
    enriched with the rule's current `display_name`."""
    payload = {
        "id": row.id,
        "rule_name": row.rule_name,
        "display_name": svc.display_name_for(row.rule_name) if svc else None,
        "severity": row.severity,
        "description": row.description,
        "metric_path": row.metric_path,
        "comparator": row.comparator,
        "threshold": row.threshold,
        "fired_at": row.fired_at,
        "resolved_at": row.resolved_at,
        "acknowledged_at": row.acknowledged_at,
        "trigger_value": row.trigger_value,
        "context": row.context,
    }
    return payload


@router.get("/alerts/active")
async def alerts_active(request: Request):
    svc = _get_alerts(request)
    if svc is None:
        return {"items": [], "silences": {}}
    items = await svc.list_active()
    silences = await svc.list_silences()
    return {
        "items": [_row_dict(r, svc) for r in items],
        "silences": silences,
    }


@router.get("/alerts/history")
async def alerts_history(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    svc = _get_alerts(request)
    if svc is None:
        return {"items": []}
    items = await svc.list_history(limit=limit)
    return {"items": [_row_dict(r, svc) for r in items]}


@router.get("/alerts/rules")
async def alerts_rules(request: Request):
    """Return the configured rule list (for UI to render rule names)."""
    svc = _get_alerts(request)
    if svc is None:
        return {"rules": []}
    return {
        "rules": [
            {
                "name": r.name,
                "display_name": r.display_name,
                "description": r.description,
                "severity": r.severity,
                "metric_path": r.metric_path,
                "comparator": r.comparator,
                "threshold": r.threshold,
                "for_seconds": r.for_seconds,
            }
            for r in svc.rules
        ],
    }


@router.post("/alerts/{event_id}/ack")
async def alerts_ack(request: Request, event_id: int):
    svc = _get_alerts(request)
    if svc is None:
        return error_response(
            request,
            status_code=503,
            code="ALERTS_DISABLED",
            message="Alert service is not running",
        )
    ok = await svc.acknowledge(event_id)
    if not ok:
        return error_response(
            request,
            status_code=404,
            code="ALERT_EVENT_NOT_FOUND",
            message=f"Alert event {event_id} not found or already acknowledged",
        )
    return {"event_id": event_id, "acknowledged": True}


class SilenceRequest(BaseModel):
    """Silence a rule for `duration_seconds` (defaults to 1 hour)."""

    duration_seconds: int = Field(default=3600, ge=60, le=7 * 24 * 3600)


@router.post("/alerts/rules/{rule_name}/silence")
async def alerts_silence(
    request: Request,
    rule_name: str,
    payload: SilenceRequest,
):
    svc = _get_alerts(request)
    if svc is None:
        return error_response(
            request,
            status_code=503,
            code="ALERTS_DISABLED",
            message="Alert service is not running",
        )
    if not any(r.name == rule_name for r in svc.rules):
        return error_response(
            request,
            status_code=404,
            code="ALERT_RULE_NOT_FOUND",
            message=f"No rule named '{rule_name}'",
        )
    until = (
        datetime.now(timezone.utc)
        + timedelta(seconds=payload.duration_seconds)
    ).isoformat()
    await svc.silence(rule_name=rule_name, until_iso=until)
    return {"rule_name": rule_name, "silenced_until": until}


@router.delete("/alerts/rules/{rule_name}/silence")
async def alerts_unsilence(request: Request, rule_name: str):
    svc = _get_alerts(request)
    if svc is None:
        return error_response(
            request,
            status_code=503,
            code="ALERTS_DISABLED",
            message="Alert service is not running",
        )
    await svc.unsilence(rule_name=rule_name)
    return {"rule_name": rule_name, "silenced_until": None}


@router.get("/alerts/stream")
async def alerts_stream(request: Request) -> StreamingResponse:
    """SSE stream of alert lifecycle events.

    Emits events: `alert_fired`, `alert_resolved`, `alert_acknowledged`,
    `alert_silenced`, `alert_unsilenced`. Clients should treat each event
    as an incremental update; full state is available via `/alerts/active`.
    """
    svc = _get_alerts(request)
    if svc is None:
        return error_response(
            request,
            status_code=503,
            code="ALERTS_DISABLED",
            message="Alert service is not running",
        )
    queue = svc.subscribe()

    # Optional SSE-counter integration so the dashboard's Live-connections
    # tile counts these connections too.
    metrics = getattr(request.app.state, "metrics", None)
    sse_counter = getattr(metrics, "sse_connections", None) if metrics else None
    if sse_counter is not None:
        sse_counter.enter("alerts")

    async def gen() -> Any:
        try:
            # Send an initial snapshot so a fresh client doesn't have to call
            # /alerts/active separately.
            try:
                active = await svc.list_active()
                yield encode_sse(
                    event="alert_snapshot",
                    data={
                        "items": [_row_dict(r, svc) for r in active],
                        "silences": await svc.list_silences(),
                    },
                )
            except Exception:
                pass
            while True:
                if await request.is_disconnected():
                    return
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Heartbeat keeps the connection alive through proxies.
                    yield b": keepalive\n\n"
                    continue
                yield encode_sse(event=str(item["event"]), data=item["data"])
        finally:
            svc.unsubscribe(queue)
            if sse_counter is not None:
                sse_counter.leave("alerts")

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
