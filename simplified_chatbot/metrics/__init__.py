"""Metrics collection package for the picobot dashboard.

Provides a `MetricsService` that aggregates samples from collectors (process,
sqlite, workspace, sse) and recorders (chat usage, api stats) into a single
current snapshot, plus per-session drill-down. Phase 1 only — no persistence.
"""

from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.metrics.recorders import (
    ApiStatsRecorder,
    ChatUsageRecorder,
    SseConnectionCounter,
)

__all__ = [
    "MetricsService",
    "ApiStatsRecorder",
    "ChatUsageRecorder",
    "SseConnectionCounter",
]
