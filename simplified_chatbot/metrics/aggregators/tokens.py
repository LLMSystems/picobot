"""Token-usage summaries derived from the ChatUsageRecorder ring buffer."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from time import monotonic

from simplified_chatbot.metrics.recorders import ChatUsageRecord


_DEFAULT_MODEL_KEY = "unknown"


@dataclass
class ModelUsageEntry:
    model: str
    tokens_in: int
    tokens_out: int


@dataclass
class TokenUsageSummary:
    tokens_in_24h: int
    tokens_out_24h: int
    by_model_24h: list[ModelUsageEntry] = field(default_factory=list)


def summarize_chat_usage(records: list[ChatUsageRecord]) -> TokenUsageSummary:
    """Roll up the recorder ring buffer over the past 24h.

    Lookback is implicit: the ring already drops anything beyond its capacity,
    so we just bound by wall-clock monotonic to skip records older than 24h
    in case the ring stayed small.
    """
    cutoff = monotonic() - 24 * 3600
    in_window = [r for r in records if r.ts >= cutoff]
    by_model: dict[str, ModelUsageEntry] = {}
    total_in = 0
    total_out = 0
    for r in in_window:
        key = r.model or _DEFAULT_MODEL_KEY
        entry = by_model.setdefault(
            key, ModelUsageEntry(model=key, tokens_in=0, tokens_out=0),
        )
        entry.tokens_in += r.prompt_tokens
        entry.tokens_out += r.completion_tokens
        total_in += r.prompt_tokens
        total_out += r.completion_tokens
    return TokenUsageSummary(
        tokens_in_24h=total_in,
        tokens_out_24h=total_out,
        by_model_24h=sorted(
            by_model.values(),
            key=lambda e: e.tokens_in + e.tokens_out,
            reverse=True,
        ),
    )


def summarize_chat_usage_for_session(
    records: list[ChatUsageRecord],
    session_id: str,
) -> TokenUsageSummary:
    return summarize_chat_usage([r for r in records if r.session_id == session_id])
