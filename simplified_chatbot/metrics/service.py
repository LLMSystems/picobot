"""MetricsService: orchestrates collectors, recorders, and aggregators."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from simplified_chatbot.metrics.aggregators.api_stats import (
    EndpointSummary,
    summarize_api_stats,
)
from simplified_chatbot.metrics.aggregators.messages import (
    MessageAggregate,
    aggregate_messages,
)
from simplified_chatbot.metrics.aggregators.sessions import (
    SessionStats,
    aggregate_sessions,
)
from simplified_chatbot.metrics.aggregators.subagents import (
    SubagentSessionStats,
    SubagentStats,
    aggregate_subagents,
    aggregate_subagents_for_session,
)
from simplified_chatbot.metrics.aggregators.tokens import (
    ModelUsageEntry,
    TokenUsageSummary,
    summarize_chat_usage,
    summarize_chat_usage_for_session,
)
from simplified_chatbot.metrics.collectors.process import ProcessCollector
from simplified_chatbot.metrics.collectors.sqlite_stats import SqliteStatsCollector
from simplified_chatbot.metrics.collectors.workspace import WorkspaceCollector
from simplified_chatbot.metrics.recorders import (
    ApiStatsRecorder,
    ChatUsageRecorder,
    SseConnectionCounter,
)
from simplified_chatbot.metrics.snapshot_store import (
    SnapshotStore,
    TimeseriesKey,
    TimeseriesPoint,
)
from simplified_chatbot.metrics.chat_usage_store import (
    ChatUsageAggregate,
    ChatUsageStore,
)
from simplified_chatbot.metrics.llm_call_store import (
    IterationStats,
    LlmCallAggregate,
    LlmCallStore,
    ModelCallAggregate,
)


_RANGE_TO_SECONDS = {
    "1h": 60 * 60,
    "24h": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60,
}

_DEFAULT_BUCKET_SECONDS = {
    "1h": 60,
    "24h": 5 * 60,
    "7d": 60 * 60,
}

_BUCKET_NAMES = {
    "1m": 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "1d": 24 * 60 * 60,
}


class MetricsService:
    """Top-level façade used by the metrics endpoints."""

    def __init__(
        self,
        *,
        db_path: str | Path | None,
        workspace_root_dir: str | Path | None,
        snapshot_store: SnapshotStore | None = None,
        chat_usage_store: ChatUsageStore | None = None,
        llm_call_store: LlmCallStore | None = None,
    ) -> None:
        self._db_path = Path(db_path).expanduser().resolve() if db_path else None
        self._process = ProcessCollector()
        self._sqlite = SqliteStatsCollector(self._db_path)
        self._workspace = WorkspaceCollector(workspace_root_dir)
        # In-memory ring is kept around for tests + as a short-term cache, but
        # the DB store (when configured) is the source of truth for summaries
        # so values survive restarts.
        self.chat_usage = ChatUsageRecorder()
        self.api_stats = ApiStatsRecorder()
        self.sse_connections = SseConnectionCounter()
        self.snapshot_store = snapshot_store
        self.chat_usage_store = chat_usage_store
        self.llm_call_store = llm_call_store
        self._chrome_status_provider = None  # set by app wiring

    def set_chrome_status_provider(self, provider) -> None:  # type: ignore[no-untyped-def]
        self._chrome_status_provider = provider

    # ---- main entry points ---------------------------------------------------

    async def build_current_snapshot(self) -> dict[str, Any]:
        """Assemble the `/metrics/current` payload."""
        process = self._process.collect()
        sqlite = await self._sqlite.collect()
        workspace = await self._workspace.collect()
        sessions = await aggregate_sessions(self._db_path)
        subagents = await aggregate_subagents(self._db_path)
        messages = await aggregate_messages(self._db_path)
        token_summary = await self._aggregate_chat_usage()
        llm_overall, llm_iterations, llm_by_model = await self._aggregate_llm_calls()
        api_summary = summarize_api_stats(
            self.api_stats.records_since(60),
            self.api_stats.records_since(3600),
        )

        return {
            "ts": _now_iso(),
            "system": _system_block(
                process=process,
                sqlite=sqlite,
                workspace=workspace,
                sse=self.sse_connections.snapshot(),
                chrome_alive=self._chrome_alive(),
            ),
            "agent": _agent_block(
                messages=messages,
                sessions=sessions,
            ),
            "subagents": _subagents_block(subagents),
            "api": _api_block(api_summary),
            "usage": _usage_block(token_summary),
            "llm": _llm_block(llm_overall, llm_iterations, llm_by_model),
        }

    async def build_session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        """Assemble the `/metrics/sessions/{id}` payload, or None if no session."""
        from simplified_chatbot.metrics.aggregators.sessions import _scalar  # type: ignore

        import aiosqlite  # local import to avoid hard dep at import time

        if self._db_path is None or not self._db_path.exists():
            return None
        async with aiosqlite.connect(str(self._db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT created_at, updated_at
                FROM session_metadata
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        created_at, updated_at = row

        messages = await aggregate_messages(self._db_path, session_id=session_id)
        sub_stats = await aggregate_subagents_for_session(self._db_path, session_id)
        chat_usage = await self._aggregate_chat_usage(session_id=session_id)
        await self._workspace.collect()  # ensure fresh cache if stale
        workspace_bytes = self._workspace.session_bytes(session_id)
        workspace_measured_at = self._workspace.measured_at

        return {
            "session_id": session_id,
            "created_at": created_at,
            "last_active_at": updated_at,
            "message_count": messages.message_count,
            "iterations_total": messages.assistant_turns,
            "tool_calls_total": messages.tool_calls_total,
            "tool_success_rate": messages.tool_success_rate,
            "tool_breakdown": [
                {
                    "name": entry.name,
                    "count": entry.count,
                    "success": entry.success,
                    "failure": entry.failure,
                    "success_rate": entry.success_rate,
                }
                for entry in sorted(
                    messages.tools_by_name.values(),
                    key=lambda e: e.count,
                    reverse=True,
                )
            ],
            "subagent_runs": sub_stats.runs_total,
            "subagent_success": sub_stats.success_total,
            "subagent_failure": sub_stats.failure_total,
            "subagent_tokens_in": sub_stats.tokens_in_total,
            "subagent_tokens_out": sub_stats.tokens_out_total,
            "subagent_tokens_by_model": [
                {"model": m, **counts}
                for m, counts in sub_stats.tokens_by_model.items()
            ],
            "chat_tokens_in": chat_usage.tokens_in_24h,
            "chat_tokens_out": chat_usage.tokens_out_24h,
            "chat_tokens_by_model": [
                {"model": e.model, "tokens_in": e.tokens_in, "tokens_out": e.tokens_out}
                for e in chat_usage.by_model_24h
            ],
            "workspace_bytes": workspace_bytes,
            "workspace_measured_at": workspace_measured_at,
        }

    async def build_history(
        self,
        *,
        range_token: str,
        series: list[str],
        bucket_token: str | None,
    ) -> dict[str, Any]:
        """Assemble the `/metrics/history` payload."""
        if self.snapshot_store is None:
            return {"range": range_token, "bucket": "1m", "series": []}
        range_seconds = _RANGE_TO_SECONDS.get(range_token)
        if range_seconds is None:
            raise ValueError(f"unknown range '{range_token}'")
        bucket_seconds = _resolve_bucket_seconds(range_token, bucket_token)
        since = (
            datetime.now(timezone.utc)
            - timedelta(seconds=range_seconds)
        ).isoformat()

        out_series: list[dict[str, Any]] = []
        for metric in series:
            grouped = await self.snapshot_store.fetch_history(
                metric=metric,
                since_iso=since,
                bucket_seconds=bucket_seconds,
            )
            for key, points in grouped:
                out_series.append(
                    {
                        "metric": key.metric,
                        "category": key.category,
                        "dim_key": key.dim_key,
                        "dim_value": key.dim_value,
                        "points": [
                            {"ts": p.ts, "value": p.value} for p in points
                        ],
                    },
                )
        bucket_label = _bucket_label(bucket_seconds)
        return {
            "range": range_token,
            "bucket": bucket_label,
            "series": out_series,
        }

    # ---- chat usage write path ---------------------------------------------

    async def record_chat_usage(
        self,
        *,
        session_id: str,
        model: str | None,
        usage: dict[str, int] | None,
    ) -> None:
        """Single entry point for chat endpoints to record a usage event.

        Writes synchronously to the in-memory ring (cheap reads + tests) AND
        awaits a DB write to `chat_usage_store` so values survive restarts.
        Awaiting is fine: chat endpoints already await seconds of model work,
        and the insert is microseconds. Fire-and-forget would leak when the
        caller's event loop tears down before the task can run.
        """
        if not usage:
            return
        self.chat_usage.record(
            session_id=session_id, model=model, usage=usage,
        )
        if self.chat_usage_store is None:
            return
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0) or (prompt + completion)
        try:
            await self.chat_usage_store.insert(
                session_id=session_id,
                model=model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            )
        except Exception:
            # Persistence failure should never break the chat flow.
            pass

    # ---- llm call write/read path ------------------------------------------

    async def record_llm_call(
        self,
        *,
        session_id: str,
        model: str | None,
        latency_ms: int,
        success: bool,
        error_type: str | None = None,
        ttft_ms: int | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Persist one LLM provider call event for availability/latency metrics.

        Best-effort: a DB failure here must not break the chat flow (the
        caller is in the request-response hot path).
        """
        if self.llm_call_store is None:
            return
        try:
            await self.llm_call_store.insert(
                session_id=session_id,
                model=model,
                latency_ms=int(latency_ms or 0),
                success=success,
                error_type=error_type,
                ttft_ms=ttft_ms,
                chat_id=chat_id,
            )
        except Exception:
            pass

    async def _aggregate_llm_calls(
        self,
    ) -> tuple[LlmCallAggregate, IterationStats, list[ModelCallAggregate]]:
        """Read 10-min LLM-call rollup + iterations + per-model breakdown.

        Window choice: a 1h rolling p95 over picobot's low-traffic baseline
        leaves the trend lines flat for an entire hour after each chat (a
        single call's effect sticks until it drops out of the window). 10 min
        keeps the chart responsive while still smoothing one-off noise.

        Returns zeros / empty lists if no store is configured. Each subquery
        is best-effort: a failure in one section shouldn't blank the others.
        """
        if self.llm_call_store is None:
            return LlmCallAggregate(), IterationStats(), []
        since = (
            datetime.now(timezone.utc) - timedelta(minutes=10)
        ).isoformat()
        try:
            overall = await self.llm_call_store.aggregate_since(since)
        except Exception:
            overall = LlmCallAggregate()
        try:
            iterations = await self.llm_call_store.aggregate_iterations_since(since)
        except Exception:
            iterations = IterationStats()
        try:
            by_model = await self.llm_call_store.aggregate_by_model_since(since)
        except Exception:
            by_model = []
        return overall, iterations, by_model

    async def _aggregate_chat_usage(
        self,
        *,
        session_id: str | None = None,
    ) -> TokenUsageSummary:
        """Read 24h chat usage from the DB store; fall back to ring if no store."""
        if self.chat_usage_store is None:
            ring = self.chat_usage.snapshot()
            if session_id is not None:
                return summarize_chat_usage_for_session(ring, session_id)
            return summarize_chat_usage(ring)
        since = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        ).isoformat()
        agg = await self.chat_usage_store.aggregate_since(
            since, session_id=session_id,
        )
        return TokenUsageSummary(
            tokens_in_24h=agg.tokens_in,
            tokens_out_24h=agg.tokens_out,
            by_model_24h=[
                ModelUsageEntry(
                    model=m.model,
                    tokens_in=m.tokens_in,
                    tokens_out=m.tokens_out,
                )
                for m in agg.by_model
            ],
        )

    # ---- internals -----------------------------------------------------------

    def _chrome_alive(self) -> bool | None:
        if self._chrome_status_provider is None:
            return None
        try:
            return bool(self._chrome_status_provider())
        except Exception:
            return None


# ---- block builders --------------------------------------------------------


def _system_block(
    *,
    process,
    sqlite,
    workspace,
    sse,
    chrome_alive,
) -> dict[str, Any]:
    return {
        "cpu_percent": process.cpu_percent,
        "rss_bytes": process.rss_bytes,
        "threads": process.threads,
        "db_file_bytes": sqlite.db_file_bytes,
        "db_row_counts": dict(sqlite.row_counts),
        "workspace_total_bytes": workspace.total_bytes,
        "workspace_session_count": workspace.session_count,
        "active_sse_connections": dict(sse),
        "chrome_alive": chrome_alive,
    }


def _agent_block(
    *,
    messages: MessageAggregate,
    sessions: SessionStats,
) -> dict[str, Any]:
    top_tools = sorted(
        messages.tools_by_name.values(),
        key=lambda e: e.count,
        reverse=True,
    )[:5]
    return {
        "sessions_total": sessions.total_sessions,
        "sessions_active_24h": sessions.active_24h,
        "sessions_new_24h": sessions.new_24h,
        "message_count_total": messages.message_count,
        "iterations_total": messages.assistant_turns,
        "tool_calls_total": messages.tool_calls_total,
        "tool_success_rate": messages.tool_success_rate,
        "top_tools": [
            {
                "name": entry.name,
                "count": entry.count,
                "success_rate": entry.success_rate,
            }
            for entry in top_tools
        ],
    }


def _subagents_block(stats: SubagentStats) -> dict[str, Any]:
    return {
        "runs_24h": stats.runs_24h,
        "success_rate_24h": stats.success_rate_24h,
        "duration_p50_ms": stats.duration_p50_ms,
        "duration_p95_ms": stats.duration_p95_ms,
        "running_now": stats.running_now,
        "longest_running_seconds": stats.longest_running_seconds,
        "tokens_in_24h": stats.tokens_in_24h,
        "tokens_out_24h": stats.tokens_out_24h,
    }


def _api_block(summary) -> dict[str, Any]:
    return {
        "qps_1m": summary.qps_1m,
        "latency_p50_ms": summary.latency_p50_ms,
        "latency_p95_ms": summary.latency_p95_ms,
        "error_4xx_rate_1h": summary.error_4xx_rate_1h,
        "error_5xx_rate_1h": summary.error_5xx_rate_1h,
        "top_endpoints_1h": [_endpoint_dict(e) for e in summary.top_endpoints_1h],
    }


def _endpoint_dict(entry: EndpointSummary) -> dict[str, Any]:
    return {
        "endpoint": entry.endpoint,
        "count": entry.count,
        "latency_p50_ms": entry.latency_p50_ms,
        "latency_p95_ms": entry.latency_p95_ms,
        "error_4xx": entry.error_4xx,
        "error_5xx": entry.error_5xx,
    }


def _llm_block(
    summary: LlmCallAggregate,
    iterations: IterationStats,
    by_model: list[ModelCallAggregate],
) -> dict[str, Any]:
    return {
        "calls_10m": summary.calls,
        "errors_10m": summary.errors,
        "timeouts_10m": summary.timeouts,
        "error_rate_10m": summary.error_rate,
        "timeout_rate_10m": summary.timeout_rate,
        "latency_p50_ms": summary.latency_p50_ms,
        "latency_p95_ms": summary.latency_p95_ms,
        "ttft_p50_ms": summary.ttft_p50_ms,
        "ttft_p95_ms": summary.ttft_p95_ms,
        "iterations_per_chat_avg": iterations.avg,
        "iterations_per_chat_max": iterations.max,
        "iterations_per_chat_p95": iterations.p95,
        "chats_10m": iterations.chats,
        "by_model_10m": [
            {
                "model": m.model,
                "calls": m.calls,
                "errors": m.errors,
                "timeouts": m.timeouts,
                "error_rate": m.error_rate,
                "timeout_rate": m.timeout_rate,
                "latency_p50_ms": m.latency_p50_ms,
                "latency_p95_ms": m.latency_p95_ms,
                "ttft_p50_ms": m.ttft_p50_ms,
                "ttft_p95_ms": m.ttft_p95_ms,
            }
            for m in by_model
        ],
    }


def _usage_block(summary: TokenUsageSummary) -> dict[str, Any]:
    return {
        "tokens_in_24h": summary.tokens_in_24h,
        "tokens_out_24h": summary.tokens_out_24h,
        "by_model_24h": [
            {"model": e.model, "tokens_in": e.tokens_in, "tokens_out": e.tokens_out}
            for e in summary.by_model_24h
        ],
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_bucket_seconds(range_token: str, bucket_token: str | None) -> int:
    if bucket_token is None:
        return _DEFAULT_BUCKET_SECONDS.get(range_token, 60)
    return _BUCKET_NAMES.get(bucket_token, _DEFAULT_BUCKET_SECONDS.get(range_token, 60))


def _bucket_label(bucket_seconds: int) -> str:
    for label, sec in _BUCKET_NAMES.items():
        if sec == bucket_seconds:
            return label
    if bucket_seconds % 3600 == 0:
        return f"{bucket_seconds // 3600}h"
    if bucket_seconds % 60 == 0:
        return f"{bucket_seconds // 60}m"
    return f"{bucket_seconds}s"
