import asyncio
from pathlib import Path

import pytest

from simplified_chatbot.runtime.session_store import (
    AioSQLiteSubagentStore,
    AioSQLiteSessionStore,
    InMemorySessionStore,
    JsonlSessionStore,
    SQLiteSessionStore,
)


def _sample_history():
    return [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]


def test_inmemory_store_round_trip():
    store = InMemorySessionStore()
    store.save_history("s1", _sample_history())

    loaded = store.load_history("s1")

    assert loaded == _sample_history()
    assert store.list_sessions() == ["s1"]


def test_inmemory_store_delete():
    store = InMemorySessionStore()
    store.save_history("s1", _sample_history())
    store.delete_session("s1")

    assert store.load_history("s1") == []
    assert store.list_sessions() == []


def test_inmemory_store_create_and_update_metadata():
    store = InMemorySessionStore()

    created = store.create_session("s1", {"title": "Draft"})
    updated = store.update_session_metadata("s1", {"title": "Renamed"})

    assert created["session_id"] == "s1"
    assert created["title"] == "Draft"
    assert updated is not None
    assert updated["title"] == "Renamed"
    assert store.list_sessions() == ["s1"]


def test_jsonl_store_round_trip(tmp_path: Path):
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save_history("chat-1", _sample_history())

    loaded = store.load_history("chat-1")

    assert loaded == _sample_history()
    assert store.list_sessions() == ["chat-1"]


def test_jsonl_store_safe_filename(tmp_path: Path):
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save_history("user/alpha:001", _sample_history())

    files = sorted((tmp_path / "sessions").glob("*.jsonl"))

    assert len(files) == 1
    assert files[0].name == "user_alpha_001.jsonl"


def test_jsonl_store_delete(tmp_path: Path):
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save_history("chat-1", _sample_history())
    store.delete_session("chat-1")

    assert store.load_history("chat-1") == []
    assert store.list_sessions() == []


def test_jsonl_store_create_and_update_metadata(tmp_path: Path):
    store = JsonlSessionStore(tmp_path / "sessions")

    created = store.create_session("chat-1", {"title": "Draft"})
    updated = store.update_session_metadata("chat-1", {"title": "Renamed"})

    assert created["session_id"] == "chat-1"
    assert created["title"] == "Draft"
    assert updated is not None
    assert updated["title"] == "Renamed"
    assert store.list_sessions() == ["chat-1"]


def test_sqlite_store_round_trip(tmp_path: Path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    store.save_history("chat-1", _sample_history())

    loaded = store.load_history("chat-1")

    assert loaded == _sample_history()
    assert store.list_sessions() == ["chat-1"]


def test_sqlite_store_overwrite_replaces_old_messages(tmp_path: Path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    store.save_history("chat-1", _sample_history())
    new_history = [
        {"role": "user", "content": "new"},
        {"role": "assistant", "content": "history"},
    ]
    store.save_history("chat-1", new_history)

    loaded = store.load_history("chat-1")

    assert loaded == new_history


def test_sqlite_store_delete(tmp_path: Path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    store.save_history("chat-1", _sample_history())
    store.delete_session("chat-1")

    assert store.load_history("chat-1") == []
    assert store.list_sessions() == []


def test_sqlite_store_list_sessions_sorted(tmp_path: Path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")
    store.save_history("b-session", _sample_history())
    store.save_history("a-session", _sample_history())

    assert store.list_sessions() == ["a-session", "b-session"]


def test_sqlite_store_create_and_update_metadata(tmp_path: Path):
    store = SQLiteSessionStore(tmp_path / "sessions.db")

    created = store.create_session("chat-1", {"title": "Draft"})
    updated = store.update_session_metadata("chat-1", {"title": "Renamed"})
    metadata = store.get_session_metadata("chat-1")

    assert created["session_id"] == "chat-1"
    assert created["title"] == "Draft"
    assert updated is not None
    assert updated["title"] == "Renamed"
    assert metadata is not None
    assert metadata["title"] == "Renamed"
    assert store.list_sessions() == ["chat-1"]


def test_aiosqlite_store_round_trip(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")

    async def _run():
        await store.save_history("chat-1", _sample_history())
        loaded = await store.load_history("chat-1")
        sessions = await store.list_sessions()
        await store.delete_session("chat-1")
        empty = await store.load_history("chat-1")
        return loaded, sessions, empty

    loaded, sessions, empty = asyncio.run(_run())
    assert loaded == _sample_history()
    assert sessions == ["chat-1"]
    assert empty == []


def test_aiosqlite_store_create_and_update_metadata(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")

    async def _run():
        created = await store.create_session("chat-1", {"title": "Draft"})
        updated = await store.update_session_metadata("chat-1", {"title": "Renamed"})
        metadata = await store.get_session_metadata("chat-1")
        sessions = await store.list_sessions()
        return created, updated, metadata, sessions

    created, updated, metadata, sessions = asyncio.run(_run())
    assert created["session_id"] == "chat-1"
    assert created["title"] == "Draft"
    assert updated is not None
    assert updated["title"] == "Renamed"
    assert metadata is not None
    assert metadata["title"] == "Renamed"
    assert sessions == ["chat-1"]


def test_aiosqlite_subagent_store_upsert_and_get_run(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents_async.db")

    async def _run():
        await store.ensure_schema()
        await store.upsert_run(
            {
                "task_id": "sub_1234",
                "parent_session_id": "session_a",
                "label": "collect refs",
                "task": "Collect references",
                "workspace": "D:/tmp/sub_1234",
                "phase": "initializing",
                "started_at": "2026-05-27T12:00:00Z",
                "finished_at": None,
                "stop_reason": None,
                "ok": None,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": None,
            }
        )
        await store.upsert_run(
            {
                "task_id": "sub_1234",
                "parent_session_id": "session_a",
                "label": "collect refs",
                "task": "Collect references",
                "workspace": "D:/tmp/sub_1234",
                "phase": "done",
                "started_at": "2026-05-27T12:00:00Z",
                "finished_at": "2026-05-27T12:00:05Z",
                "stop_reason": "completed",
                "ok": True,
                "error": None,
                "usage": {"prompt_tokens": 12},
                "tool_events": [{"id": "tc1", "name": "glob", "status": "ok"}],
                "final_content": "Found files",
            }
        )
        return await store.get_run("sub_1234")

    payload = asyncio.run(_run())
    assert payload is not None
    assert payload["task_id"] == "sub_1234"
    assert payload["phase"] == "done"
    assert payload["ok"] is True
    assert payload["usage"] == {"prompt_tokens": 12}
    assert payload["tool_events"][0]["name"] == "glob"
    assert payload["final_content"] == "Found files"


def test_aiosqlite_subagent_store_lists_runs_by_session_and_phase(tmp_path: Path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSubagentStore(tmp_path / "subagents_async.db")

    async def _run():
        await store.upsert_run(
            {
                "task_id": "sub_done",
                "parent_session_id": "session_a",
                "label": "done task",
                "task": "Done task",
                "workspace": None,
                "phase": "done",
                "started_at": "2026-05-27T12:00:05Z",
                "finished_at": "2026-05-27T12:00:06Z",
                "stop_reason": "completed",
                "ok": True,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": "done",
            }
        )
        await store.upsert_run(
            {
                "task_id": "sub_running",
                "parent_session_id": "session_a",
                "label": "running task",
                "task": "Running task",
                "workspace": None,
                "phase": "running",
                "started_at": "2026-05-27T12:00:10Z",
                "finished_at": None,
                "stop_reason": None,
                "ok": None,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": None,
            }
        )
        await store.upsert_run(
            {
                "task_id": "sub_other",
                "parent_session_id": "session_b",
                "label": "other task",
                "task": "Other task",
                "workspace": None,
                "phase": "done",
                "started_at": "2026-05-27T12:00:03Z",
                "finished_at": "2026-05-27T12:00:04Z",
                "stop_reason": "completed",
                "ok": True,
                "error": None,
                "usage": {},
                "tool_events": [],
                "final_content": "other",
            }
        )
        session_a = await store.list_runs(parent_session_id="session_a")
        running = await store.list_runs(parent_session_id="session_a", phase="running")
        return session_a, running

    session_a, running = asyncio.run(_run())
    assert [item["task_id"] for item in session_a] == ["sub_running", "sub_done"]
    assert [item["task_id"] for item in running] == ["sub_running"]
