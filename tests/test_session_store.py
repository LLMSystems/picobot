import asyncio
from pathlib import Path

import pytest

from simplified_chatbot.runtime.session_store import (
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
