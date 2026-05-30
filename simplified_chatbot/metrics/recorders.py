"""In-memory ring-buffer recorders for live metrics.

These hold short-lived data that the rest of the snapshot pipeline reads from.
Phase 1 only — Phase 2 will flush their aggregates into the snapshot table.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Iterable


@dataclass(frozen=True)
class ChatUsageRecord:
    ts: float  # monotonic seconds
    session_id: str
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ApiStatsRecord:
    ts: float  # monotonic seconds
    endpoint: str  # templated path, e.g. "/sessions/{session_id}"
    status_code: int
    duration_ms: float


class ChatUsageRecorder:
    """Bounded ring of recent chat-call usage records.

    Lives entirely in memory; lost on restart. Phase 2 will mirror aggregates
    into the snapshot table so historical totals survive.
    """

    def __init__(self, max_records: int = 10_000) -> None:
        self._records: deque[ChatUsageRecord] = deque(maxlen=max_records)
        self._lock = Lock()

    def record(
        self,
        *,
        session_id: str,
        model: str | None,
        usage: dict[str, int] | None,
    ) -> None:
        if not usage:
            return
        prompt = int(usage.get("prompt_tokens", 0) or 0)
        completion = int(usage.get("completion_tokens", 0) or 0)
        total = int(usage.get("total_tokens", 0) or 0) or (prompt + completion)
        with self._lock:
            self._records.append(
                ChatUsageRecord(
                    ts=monotonic(),
                    session_id=session_id,
                    model=model,
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                ),
            )

    def snapshot(self) -> list[ChatUsageRecord]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class ApiStatsRecorder:
    """Bounded ring of recent (endpoint, status, duration) tuples.

    Snapshot aggregates count, p50/p95 latency, and 4xx/5xx rates over a
    configurable look-back window.
    """

    def __init__(self, max_records: int = 10_000) -> None:
        self._records: deque[ApiStatsRecord] = deque(maxlen=max_records)
        self._lock = Lock()

    def record(self, *, endpoint: str, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self._records.append(
                ApiStatsRecord(
                    ts=monotonic(),
                    endpoint=endpoint,
                    status_code=status_code,
                    duration_ms=duration_ms,
                ),
            )

    def snapshot(self) -> list[ApiStatsRecord]:
        with self._lock:
            return list(self._records)

    def records_since(self, lookback_seconds: float) -> list[ApiStatsRecord]:
        cutoff = monotonic() - lookback_seconds
        with self._lock:
            return [r for r in self._records if r.ts >= cutoff]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


@dataclass
class _CounterEntry:
    count: int = 0


class SseConnectionCounter:
    """Process-wide counter for active SSE connections, partitioned by stream."""

    def __init__(self) -> None:
        self._counts: dict[str, _CounterEntry] = {}
        self._lock = Lock()

    def enter(self, stream: str) -> None:
        with self._lock:
            self._counts.setdefault(stream, _CounterEntry()).count += 1

    def leave(self, stream: str) -> None:
        with self._lock:
            entry = self._counts.get(stream)
            if entry is None:
                return
            entry.count = max(0, entry.count - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {k: v.count for k, v in self._counts.items()}


def percentile(values: Iterable[float], p: float) -> float:
    """Return the p-th percentile (0..1) of values using nearest-rank."""
    sorted_vals = sorted(values)
    if not sorted_vals:
        return 0.0
    if p <= 0:
        return sorted_vals[0]
    if p >= 1:
        return sorted_vals[-1]
    rank = max(0, min(len(sorted_vals) - 1, int(round(p * (len(sorted_vals) - 1)))))
    return sorted_vals[rank]
