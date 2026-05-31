"""Build SnapshotRow lists from a current MetricsService snapshot.

Kept separate from snapshot_task so the row-building logic stays unit-testable
without an event loop.
"""

from __future__ import annotations

from typing import Any, Iterable

from simplified_chatbot.metrics.snapshot_store import SnapshotRow


_SYSTEM_GAUGES = (
    "cpu_percent",
    "rss_bytes",
    "threads",
    "db_file_bytes",
    "workspace_total_bytes",
    "workspace_session_count",
)


_AGENT_GAUGES = (
    "sessions_total",
    "sessions_active_24h",
    "sessions_new_24h",
    "message_count_total",
    "iterations_total",
    "tool_calls_total",
    "tool_success_rate",
)

_SUBAGENT_GAUGES = (
    "runs_24h",
    "success_rate_24h",
    "duration_p50_ms",
    "duration_p95_ms",
    "running_now",
    "tokens_in_24h",
    "tokens_out_24h",
)

_API_GAUGES = (
    "qps_1m",
    "latency_p50_ms",
    "latency_p95_ms",
    "error_4xx_rate_1h",
    "error_5xx_rate_1h",
)

_USAGE_TOTALS = ("tokens_in_24h", "tokens_out_24h")

_LLM_GAUGES = (
    "calls_10m",
    "errors_10m",
    "timeouts_10m",
    "error_rate_10m",
    "timeout_rate_10m",
    "latency_p50_ms",
    "latency_p95_ms",
    "ttft_p50_ms",
    "ttft_p95_ms",
    "iterations_per_chat_avg",
    "iterations_per_chat_p95",
    "chats_10m",
)

_PER_SESSION_GAUGES = (
    "message_count",
    "iterations_total",
    "tool_calls_total",
    "chat_tokens_in",
    "chat_tokens_out",
    "subagent_runs",
    "subagent_tokens_in",
    "subagent_tokens_out",
)


def build_global_rows(
    *,
    ts: str,
    snapshot: dict[str, Any],
) -> list[SnapshotRow]:
    """Translate one `MetricsService.build_current_snapshot()` payload into rows."""
    rows: list[SnapshotRow] = []
    rows.extend(_gauges(ts, "system", snapshot.get("system", {}), _SYSTEM_GAUGES))
    rows.extend(_gauges(ts, "agent", snapshot.get("agent", {}), _AGENT_GAUGES))
    rows.extend(
        _gauges(ts, "subagents", snapshot.get("subagents", {}), _SUBAGENT_GAUGES),
    )
    rows.extend(_gauges(ts, "api", snapshot.get("api", {}), _API_GAUGES))
    rows.extend(_gauges(ts, "usage", snapshot.get("usage", {}), _USAGE_TOTALS))
    rows.extend(_gauges(ts, "llm", snapshot.get("llm", {}), _LLM_GAUGES))

    sse_block = (snapshot.get("system") or {}).get("active_sse_connections") or {}
    for stream, count in sse_block.items():
        rows.append(
            SnapshotRow(
                ts=ts,
                category="system",
                metric="active_sse_connections",
                dim_key="stream",
                dim_value=str(stream),
                value_num=_as_float(count),
            ),
        )

    for entry in (snapshot.get("usage") or {}).get("by_model_24h", []) or []:
        model = entry.get("model")
        if not model:
            continue
        rows.append(
            SnapshotRow(
                ts=ts,
                category="usage",
                metric="tokens_in_24h",
                dim_key="model",
                dim_value=str(model),
                value_num=_as_float(entry.get("tokens_in")),
            ),
        )
        rows.append(
            SnapshotRow(
                ts=ts,
                category="usage",
                metric="tokens_out_24h",
                dim_key="model",
                dim_value=str(model),
                value_num=_as_float(entry.get("tokens_out")),
            ),
        )

    for endpoint_entry in (snapshot.get("api") or {}).get("top_endpoints_1h", []) or []:
        endpoint = endpoint_entry.get("endpoint")
        if not endpoint:
            continue
        for metric_key in ("count", "latency_p50_ms", "latency_p95_ms", "error_4xx", "error_5xx"):
            rows.append(
                SnapshotRow(
                    ts=ts,
                    category="api",
                    metric=f"endpoint_{metric_key}",
                    dim_key="endpoint",
                    dim_value=str(endpoint),
                    value_num=_as_float(endpoint_entry.get(metric_key)),
                ),
            )

    return rows


def build_session_rows(
    *,
    ts: str,
    session_id: str,
    session_snapshot: dict[str, Any],
) -> list[SnapshotRow]:
    """Translate one per-session snapshot payload into rows.

    Only the small fixed set of per-session gauges is written — see
    `_PER_SESSION_GAUGES`. Each row is tagged with `dim_key='session_id'`.
    """
    rows: list[SnapshotRow] = []
    for metric in _PER_SESSION_GAUGES:
        if metric not in session_snapshot:
            continue
        rows.append(
            SnapshotRow(
                ts=ts,
                category="per_session",
                metric=metric,
                dim_key="session_id",
                dim_value=session_id,
                value_num=_as_float(session_snapshot.get(metric)),
            ),
        )
    return rows


def _gauges(
    ts: str,
    category: str,
    block: dict[str, Any],
    metrics: Iterable[str],
) -> list[SnapshotRow]:
    out: list[SnapshotRow] = []
    for metric in metrics:
        value = block.get(metric)
        if value is None:
            continue
        out.append(
            SnapshotRow(
                ts=ts,
                category=category,
                metric=metric,
                value_num=_as_float(value),
            ),
        )
    return out


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
