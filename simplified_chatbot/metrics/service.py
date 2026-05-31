"""MetricsService: orchestrates collectors, recorders, and aggregators."""

from __future__ import annotations

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
    ) -> None:
        self._db_path = Path(db_path).expanduser().resolve() if db_path else None
        self._process = ProcessCollector()
        self._sqlite = SqliteStatsCollector(self._db_path)
        self._workspace = WorkspaceCollector(workspace_root_dir)
        self.chat_usage = ChatUsageRecorder()
        self.api_stats = ApiStatsRecorder()
        self.sse_connections = SseConnectionCounter()
        self.snapshot_store = snapshot_store
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
        chat_usage = self.chat_usage.snapshot()
        token_summary = summarize_chat_usage(chat_usage)
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
        chat_usage = summarize_chat_usage_for_session(
            self.chat_usage.snapshot(), session_id,
        )
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
