"""Background task that periodically persists snapshots into metrics_snapshots."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any

from simplified_chatbot.metrics.aggregators.sessions import list_active_session_ids
from simplified_chatbot.metrics.snapshot_store import SnapshotStore
from simplified_chatbot.metrics.snapshot_writer import (
    build_global_rows,
    build_session_rows,
)


logger = logging.getLogger("picobot.metrics.snapshot")


class SnapshotTask:
    """Drives one snapshot per `interval_seconds`, plus periodic pruning."""

    def __init__(
        self,
        *,
        service: "Any",  # MetricsService (typed loosely to avoid cycle)
        store: SnapshotStore,
        db_path: str | None,
        interval_seconds: int = 60,
        retention_days: int = 7,
        prune_every_ticks: int = 10,
        per_session_lookback_hours: int = 24,
        per_session_limit: int = 100,
        alert_service: "Any" = None,  # optional AlertService
    ) -> None:
        self._service = service
        self._store = store
        self._db_path = db_path
        self._interval = max(5, interval_seconds)
        self._retention_days = max(1, retention_days)
        self._prune_every = max(1, prune_every_ticks)
        self._lookback_hours = per_session_lookback_hours
        self._per_session_limit = per_session_limit
        self._alert_service = alert_service
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._tick_count = 0

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._store.ensure_schema()
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def tick_once(self) -> None:
        """Public for tests: run one snapshot cycle immediately."""
        await self._capture_once()

    async def _run_loop(self) -> None:
        # First snapshot fires after one interval, not immediately, so server
        # startup doesn't get extra load while everything is still warming up.
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._interval,
                    )
                    return  # stop requested mid-sleep
                except asyncio.TimeoutError:
                    pass
                await self._capture_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive
            logger.exception("snapshot loop crashed")

    async def _capture_once(self) -> None:
        try:
            ts = datetime.now(timezone.utc).isoformat()
            snapshot = await self._service.build_current_snapshot()
            rows = build_global_rows(ts=ts, snapshot=snapshot)
            session_ids = await list_active_session_ids(
                self._db_path,
                lookback_hours=self._lookback_hours,
                limit=self._per_session_limit,
            )
            for sid in session_ids:
                per = await self._service.build_session_snapshot(sid)
                if not per:
                    continue
                rows.extend(build_session_rows(ts=ts, session_id=sid, session_snapshot=per))
            await self._store.insert_rows(rows)

            # Evaluate alert rules against the same snapshot so timestamps
            # line up with the trend charts.
            if self._alert_service is not None:
                try:
                    await self._alert_service.evaluate(snapshot)
                except Exception:
                    logger.exception("alert evaluation failed")

            self._tick_count += 1
            if self._tick_count % self._prune_every == 0:
                pruned = await self._store.prune_older_than(
                    retention_days=self._retention_days,
                )
                if pruned:
                    logger.info("pruned %d old metrics rows", pruned)
                if self._alert_service is not None:
                    try:
                        await self._alert_service.prune()
                    except Exception:
                        logger.exception("alert prune failed")
        except Exception:
            logger.exception("snapshot tick failed")
