"""AlertService — evaluates rules against a metrics snapshot and persists state.

The service is single-process and stateless across restarts in terms of
"pending" timers (the `for_seconds` countdown resets) but **alert events**
themselves are persistent. A firing alert that survives a restart will still
be reported as active until either it resolves or 7 days elapse.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from simplified_chatbot.alerts.events_store import AlertEventRow, AlertEventsStore
from simplified_chatbot.alerts.rules import AlertRule, resolve_metric_value


@dataclass
class _PendingState:
    """In-memory tracking for a rule between evaluations."""

    condition_true_since: float | None = None  # monotonic seconds when first satisfied
    active_event_id: int | None = None         # row id of current firing event (if any)


@dataclass
class AlertEvaluationResult:
    """Outcome of one evaluation cycle — useful for tests + SSE broadcasting."""

    fired: list[AlertEventRow] = field(default_factory=list)
    resolved: list[AlertEventRow] = field(default_factory=list)


class AlertService:
    def __init__(
        self,
        *,
        store: AlertEventsStore,
        rules: list[AlertRule],
        retention_days: int = 30,
    ) -> None:
        self.store = store
        self.rules = rules
        self.retention_days = retention_days
        self._pending: dict[str, _PendingState] = {
            r.name: _PendingState() for r in rules
        }
        # SSE subscribers — each holds a queue of dict events. Producers drop
        # events on full queues rather than blocking the evaluation loop.
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    async def hydrate_from_db(self) -> None:
        """Reattach `active_event_id` for rules whose previous firing survived restart."""
        await self.store.ensure_schema()
        for row in await self.store.list_active():
            if row.rule_name in self._pending:
                self._pending[row.rule_name].active_event_id = row.id

    def display_name_for(self, rule_name: str) -> str | None:
        """Return the optional `display_name` for a rule, falling back to None.

        Display names live only in alerts.yaml — they aren't persisted into
        alert_events because (a) renaming a rule shouldn't require a DB
        migration and (b) the latest yaml is the single source of truth.
        """
        for r in self.rules:
            if r.name == rule_name:
                return r.display_name
        return None

    def row_dict(self, row: AlertEventRow) -> dict[str, Any]:
        """Same as `_row_dict` but enriched with the current display_name."""
        payload = _row_dict(row)
        payload["display_name"] = self.display_name_for(row.rule_name)
        return payload

    async def evaluate(self, snapshot: dict[str, Any]) -> AlertEvaluationResult:
        """Run all rules against one snapshot; return new firings + resolutions."""
        result = AlertEvaluationResult()
        now_iso = datetime.now(timezone.utc).isoformat()
        # We use monotonic for `for_seconds` damping — safe across DST etc.
        from time import monotonic
        now_mono = monotonic()

        silences = await self.store.active_silences()

        for rule in self.rules:
            value = resolve_metric_value(snapshot, rule.metric_path)
            condition_met = rule.evaluate(value)
            state = self._pending[rule.name]

            if condition_met:
                if state.condition_true_since is None:
                    state.condition_true_since = now_mono
                duration = now_mono - state.condition_true_since
                ready_to_fire = duration >= max(0, rule.for_seconds)
                if state.active_event_id is None and ready_to_fire:
                    if rule.name in silences:
                        # Currently silenced — don't fire, but keep timer so we
                        # fire immediately once the silence expires.
                        continue
                    trigger_num = _coerce_float(value)
                    event_id = await self.store.insert_firing(
                        rule_name=rule.name,
                        severity=rule.severity,
                        description=rule.description,
                        metric_path=rule.metric_path,
                        comparator=rule.comparator,
                        threshold=rule.threshold,
                        fired_at=now_iso,
                        trigger_value=trigger_num,
                        context={"value": value},
                    )
                    state.active_event_id = event_id
                    fired_row = AlertEventRow(
                        id=event_id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        description=rule.description,
                        metric_path=rule.metric_path,
                        comparator=rule.comparator,
                        threshold=str(rule.threshold),
                        fired_at=now_iso,
                        resolved_at=None,
                        acknowledged_at=None,
                        trigger_value=trigger_num,
                        context={"value": value},
                    )
                    result.fired.append(fired_row)
                    self._broadcast("alert_fired", self.row_dict(fired_row))
            else:
                # Condition no longer met — drop the timer + resolve if firing.
                state.condition_true_since = None
                if state.active_event_id is not None:
                    event_id = state.active_event_id
                    await self.store.mark_resolved(
                        event_id=event_id, resolved_at=now_iso,
                    )
                    state.active_event_id = None
                    # Cheap re-fetch so the SSE consumer sees a complete row.
                    for row in await self.store.list_history(limit=1):
                        if row.id == event_id:
                            result.resolved.append(row)
                            self._broadcast("alert_resolved", self.row_dict(row))
                            break

        return result

    async def acknowledge(self, event_id: int) -> bool:
        ok = await self.store.mark_acknowledged(
            event_id=event_id,
            acked_at=datetime.now(timezone.utc).isoformat(),
        )
        if ok:
            # Re-fetch so subscribers get the updated row (ack timestamp).
            for row in await self.store.list_history(limit=1):
                if row.id == event_id:
                    self._broadcast("alert_acknowledged", self.row_dict(row))
                    break
        return ok

    async def silence(self, *, rule_name: str, until_iso: str) -> None:
        await self.store.set_silence(
            rule_name=rule_name, silenced_until=until_iso,
        )
        self._broadcast(
            "alert_silenced",
            {"rule_name": rule_name, "silenced_until": until_iso},
        )

    async def unsilence(self, *, rule_name: str) -> None:
        await self.store.clear_silence(rule_name=rule_name)
        self._broadcast(
            "alert_unsilenced",
            {"rule_name": rule_name},
        )

    # ---- subscriber wiring --------------------------------------------------

    def subscribe(self, maxsize: int = 64) -> asyncio.Queue[dict[str, Any]]:
        """Register a new SSE subscriber. Returns a queue of `{event, data}`."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def _broadcast(self, event: str, data: dict[str, Any]) -> None:
        """Best-effort fanout; drops on full queues to avoid back-pressure."""
        payload = {"event": event, "data": data}
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Subscriber too slow — silently drop. The client can resync
                # via /alerts/active on reconnect.
                continue

    async def list_active(self) -> list[AlertEventRow]:
        return await self.store.list_active()

    async def list_history(self, *, limit: int = 100) -> list[AlertEventRow]:
        return await self.store.list_history(limit=limit)

    async def list_silences(self) -> dict[str, str]:
        return await self.store.active_silences()

    async def prune(self) -> int:
        return await self.store.prune_older_than(retention_days=self.retention_days)


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_dict(row: AlertEventRow) -> dict[str, Any]:
    """Same shape as the REST endpoint — keep the SSE payload consistent."""
    return {
        "id": row.id,
        "rule_name": row.rule_name,
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
