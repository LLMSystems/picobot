"""Roll up ApiStatsRecorder records into endpoint-level summaries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from simplified_chatbot.metrics.recorders import ApiStatsRecord, percentile


@dataclass
class EndpointSummary:
    endpoint: str
    count: int
    latency_p50_ms: float
    latency_p95_ms: float
    error_4xx: int
    error_5xx: int


@dataclass
class ApiStatsSummary:
    qps_1m: float
    latency_p50_ms: float
    latency_p95_ms: float
    error_4xx_rate_1h: float
    error_5xx_rate_1h: float
    top_endpoints_1h: list[EndpointSummary] = field(default_factory=list)


def summarize_api_stats(
    records_1m: list[ApiStatsRecord],
    records_1h: list[ApiStatsRecord],
    *,
    top_n: int = 5,
) -> ApiStatsSummary:
    qps = len(records_1m) / 60.0
    latencies_1m = [r.duration_ms for r in records_1m]
    p50 = percentile(latencies_1m, 0.5)
    p95 = percentile(latencies_1m, 0.95)

    total_1h = len(records_1h) or 1
    err_4xx = sum(1 for r in records_1h if 400 <= r.status_code < 500)
    err_5xx = sum(1 for r in records_1h if r.status_code >= 500)

    by_endpoint: dict[str, list[ApiStatsRecord]] = defaultdict(list)
    for r in records_1h:
        by_endpoint[r.endpoint].append(r)

    summaries: list[EndpointSummary] = []
    for endpoint, recs in by_endpoint.items():
        durations = [r.duration_ms for r in recs]
        summaries.append(
            EndpointSummary(
                endpoint=endpoint,
                count=len(recs),
                latency_p50_ms=percentile(durations, 0.5),
                latency_p95_ms=percentile(durations, 0.95),
                error_4xx=sum(1 for r in recs if 400 <= r.status_code < 500),
                error_5xx=sum(1 for r in recs if r.status_code >= 500),
            ),
        )
    summaries.sort(key=lambda s: s.count, reverse=True)
    return ApiStatsSummary(
        qps_1m=qps,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        error_4xx_rate_1h=err_4xx / total_1h if records_1h else 0.0,
        error_5xx_rate_1h=err_5xx / total_1h if records_1h else 0.0,
        top_endpoints_1h=summaries[:top_n],
    )
