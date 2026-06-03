import asyncio
import sqlite3

import pytest

pytest.importorskip("aiosqlite")

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.metrics.collectors.sqlite_stats import SqliteStatsCollector
from simplified_chatbot.metrics.service import MetricsService
from simplified_chatbot.runtime.session_store import (
    AioSQLiteSessionStore,
    AioSQLiteSubagentEventStore,
    AioSQLiteSubagentStore,
)


class _DummyChatbot:
    def __init__(self) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
        )


def test_sqlite_stats_collector_collects_known_table_counts(tmp_path):
    db_path = tmp_path / "sessions.db"

    async def seed() -> None:
        store = AioSQLiteSessionStore(db_path)
        await store.create_session("s1", {"title": "demo"})
        await store.save_history(
            "s1",
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ],
        )

        subagent_store = AioSQLiteSubagentStore(db_path)
        await subagent_store.upsert_run(
            {
                "task_id": "sub_1",
                "parent_session_id": "s1",
                "label": "collect refs",
                "task": "Collect references",
                "workspace": None,
                "phase": "done",
                "started_at": "2026-06-03T10:00:00Z",
                "finished_at": "2026-06-03T10:00:10Z",
                "stop_reason": "stop",
                "ok": True,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": "done",
                "model": "gpt-5-mini",
            },
        )

        event_store = AioSQLiteSubagentEventStore(db_path)
        await event_store.append_event(
            task_id="sub_1",
            parent_session_id="s1",
            event_type="subagent_completed",
            payload={"ok": True},
            created_at="2026-06-03T10:00:10Z",
        )

    asyncio.run(seed())

    sample = asyncio.run(SqliteStatsCollector(db_path).collect())

    assert sample.db_file_bytes is not None
    assert sample.db_file_bytes > 0
    assert sample.row_counts == {
        "session_messages": 2,
        "session_metadata": 1,
        "subagent_runs": 1,
        "subagent_events": 1,
    }


def test_sqlite_stats_collector_skips_missing_tables(tmp_path):
    db_path = tmp_path / "partial.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE misc (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    sample = asyncio.run(SqliteStatsCollector(db_path).collect())

    assert sample.db_file_bytes is not None
    assert sample.row_counts == {}


def test_metrics_service_exposes_db_row_counts_and_chrome_status(tmp_path):
    db_path = tmp_path / "sessions.db"

    async def seed() -> None:
        store = AioSQLiteSessionStore(db_path)
        await store.save_history(
            "s1",
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ],
        )

    asyncio.run(seed())

    service = MetricsService(
        db_path=db_path,
        workspace_root_dir=tmp_path / "workspaces",
    )
    service.set_chrome_status_provider(lambda: True)

    snapshot = asyncio.run(service.build_current_snapshot())

    assert snapshot["system"]["chrome_alive"] is True
    assert snapshot["system"]["db_row_counts"]["session_messages"] == 2
    assert snapshot["system"]["db_row_counts"]["session_metadata"] == 1
