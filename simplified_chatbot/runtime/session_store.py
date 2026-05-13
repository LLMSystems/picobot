"""Session history stores for local runtime."""

from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from simplified_chatbot.agent.types import Message

try:
    import aiosqlite  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    aiosqlite = None  # type: ignore[assignment]


class SessionStore(ABC):
    """Abstract storage for session histories."""

    @abstractmethod
    def load_history(self, session_id: str) -> list[Message]:
        """Load one session history."""

    @abstractmethod
    def save_history(self, session_id: str, history: list[Message]) -> None:
        """Persist one session history."""

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        """Delete one session history."""

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """List known session identifiers."""


class AsyncSessionStore(ABC):
    """Async abstract storage for session histories."""

    @abstractmethod
    async def load_history(self, session_id: str) -> list[Message]:
        """Load one session history."""

    @abstractmethod
    async def save_history(self, session_id: str, history: list[Message]) -> None:
        """Persist one session history."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete one session history."""

    @abstractmethod
    async def list_sessions(self) -> list[str]:
        """List known session identifiers."""


class InMemorySessionStore(SessionStore):
    """Simple in-memory session store."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}

    def load_history(self, session_id: str) -> list[Message]:
        history = self._sessions.get(session_id, [])
        return [dict(item) for item in history]

    def save_history(self, session_id: str, history: list[Message]) -> None:
        self._sessions[session_id] = [dict(item) for item in history]

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return sorted(self._sessions.keys())


class JsonlSessionStore(SessionStore):
    """File-backed store: one session per JSONL file."""

    _SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")

    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).expanduser().resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _safe_name(cls, session_id: str) -> str:
        normalized = cls._SAFE_RE.sub("_", session_id.strip())
        normalized = normalized.strip("._")
        return normalized or "session"

    def _path_for(self, session_id: str) -> Path:
        return self.root_dir / f"{self._safe_name(session_id)}.jsonl"

    def load_history(self, session_id: str) -> list[Message]:
        path = self._path_for(session_id)
        if not path.exists():
            return []
        messages: list[Message] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                continue
            messages.append(payload)
        return messages

    def save_history(self, session_id: str, history: list[Message]) -> None:
        path = self._path_for(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            for message in history:
                fh.write(json.dumps(message, ensure_ascii=False))
                fh.write("\n")
        tmp_path.replace(path)

    def delete_session(self, session_id: str) -> None:
        path = self._path_for(session_id)
        if path.exists():
            path.unlink()

    def list_sessions(self) -> list[str]:
        names = [item.stem for item in self.root_dir.glob("*.jsonl") if item.is_file()]
        return sorted(names)


class SQLiteSessionStore(SessionStore):
    """SQLite-backed session store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_messages (
                    session_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, position)
                )
                """,
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_session_messages_session
                ON session_messages(session_id)
                """,
            )

    def load_history(self, session_id: str) -> list[Message]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT payload
                FROM session_messages
                WHERE session_id = ?
                ORDER BY position ASC
                """,
                (session_id,),
            )
            rows = cursor.fetchall()

        messages: list[Message] = []
        for (payload,) in rows:
            obj = json.loads(payload)
            if isinstance(obj, dict):
                messages.append(obj)
        return messages

    def save_history(self, session_id: str, history: list[Message]) -> None:
        rows = [
            (session_id, index, json.dumps(message, ensure_ascii=False))
            for index, message in enumerate(history)
        ]
        with self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            if rows:
                conn.executemany(
                    """
                    INSERT INTO session_messages (session_id, position, payload)
                    VALUES (?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )

    def list_sessions(self) -> list[str]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT session_id
                FROM session_messages
                ORDER BY session_id ASC
                """,
            )
            rows = cursor.fetchall()
        return [str(session_id) for (session_id,) in rows]


class AioSQLiteSessionStore(AsyncSessionStore):
    """Async SQLite-backed session store using aiosqlite."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "AioSQLiteSessionStore requires 'aiosqlite'. Install with: pip install aiosqlite",
            )
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._init_lock: Any = None

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            import asyncio

            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            async with aiosqlite.connect(str(self.db_path)) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_messages (
                        session_id TEXT NOT NULL,
                        position INTEGER NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY (session_id, position)
                    )
                    """,
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_session_messages_session
                    ON session_messages(session_id)
                    """,
                )
                await conn.commit()
            self._initialized = True

    async def load_history(self, session_id: str) -> list[Message]:
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT payload
                FROM session_messages
                WHERE session_id = ?
                ORDER BY position ASC
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        messages: list[Message] = []
        for (payload,) in rows:
            obj = json.loads(payload)
            if isinstance(obj, dict):
                messages.append(obj)
        return messages

    async def save_history(self, session_id: str, history: list[Message]) -> None:
        await self._ensure_initialized()
        rows = [
            (session_id, index, json.dumps(message, ensure_ascii=False))
            for index, message in enumerate(history)
        ]
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute("BEGIN")
            await conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            if rows:
                await conn.executemany(
                    """
                    INSERT INTO session_messages (session_id, position, payload)
                    VALUES (?, ?, ?)
                    """,
                    rows,
                )
            await conn.commit()

    async def delete_session(self, session_id: str) -> None:
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            await conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            await conn.commit()

    async def list_sessions(self) -> list[str]:
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self.db_path)) as conn:
            cursor = await conn.execute(
                """
                SELECT DISTINCT session_id
                FROM session_messages
                ORDER BY session_id ASC
                """,
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [str(session_id) for (session_id,) in rows]
