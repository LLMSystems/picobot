"""Unit tests for in-memory recorders used by the dashboard MVP."""

from __future__ import annotations

from simplified_chatbot.metrics.recorders import (
    ApiStatsRecorder,
    ChatUsageRecorder,
    SseConnectionCounter,
    percentile,
)


def test_chat_usage_recorder_accumulates_records():
    r = ChatUsageRecorder()
    r.record(
        session_id="s1",
        model="gpt-x",
        usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
    )
    r.record(
        session_id="s2",
        model="gpt-x",
        usage={"prompt_tokens": 1, "completion_tokens": 2},
    )
    snap = r.snapshot()
    assert len(snap) == 2
    assert snap[0].session_id == "s1"
    assert snap[0].prompt_tokens == 5
    assert snap[1].total_tokens == 3, "total_tokens falls back to prompt+completion"


def test_chat_usage_recorder_ignores_empty_usage():
    r = ChatUsageRecorder()
    r.record(session_id="s1", model="gpt", usage=None)
    r.record(session_id="s1", model="gpt", usage={})
    assert r.snapshot() == []


def test_chat_usage_recorder_respects_ring_capacity():
    r = ChatUsageRecorder(max_records=2)
    for i in range(5):
        r.record(
            session_id=f"s{i}",
            model="m",
            usage={"prompt_tokens": 1, "completion_tokens": 1},
        )
    snap = r.snapshot()
    assert len(snap) == 2
    assert snap[0].session_id == "s3"
    assert snap[1].session_id == "s4"


def test_api_stats_recorder_records_since_filters_old():
    r = ApiStatsRecorder()
    r.record(endpoint="/x", status_code=200, duration_ms=10.0)
    # Reach into the record to simulate an old one.
    r._records[0] = r._records[0].__class__(  # type: ignore[misc]
        ts=-10_000,
        endpoint="/x",
        status_code=200,
        duration_ms=10.0,
    )
    r.record(endpoint="/y", status_code=500, duration_ms=20.0)

    recent = r.records_since(60)
    assert len(recent) == 1
    assert recent[0].endpoint == "/y"


def test_sse_connection_counter_tracks_streams():
    c = SseConnectionCounter()
    assert c.snapshot() == {}
    c.enter("chat")
    c.enter("chat")
    c.enter("session_events")
    assert c.snapshot() == {"chat": 2, "session_events": 1}
    c.leave("chat")
    c.leave("chat")
    c.leave("chat")  # over-leave is clamped to zero, not negative
    assert c.snapshot() == {"chat": 0, "session_events": 1}


def test_percentile_handles_empty_and_boundaries():
    assert percentile([], 0.5) == 0.0
    assert percentile([7.0], 0.5) == 7.0
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 5.0
    assert percentile(values, 0.5) == 3.0
