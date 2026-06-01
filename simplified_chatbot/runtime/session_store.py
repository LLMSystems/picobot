"""Session history stores for local runtime."""

from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simplified_chatbot.agent.types import Message

try:
    import aiosqlite  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.runtime.sqlite_pragmas import open_async


@dataclass(slots=True)
class SessionMemoryRow:
    """Rolling memory summary for one chat session."""

    session_id: str
    summary: str
    compacted_message_count: int
    updated_at: str


@dataclass(slots=True)
class SessionMemoryNoteRow:
    """One user-managed memory note attached to a chat session."""

    id: int
    session_id: str
    kind: str
    content: str
    created_at: str
    updated_at: str
    archived_at: str | None = None


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

    def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        """Return optional metadata for one session."""
        return None

    def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Create or initialize one session metadata record."""
        return dict(metadata or {})

    def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        """Update one session metadata record."""
        return None


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

    async def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        """Return optional metadata for one session."""
        return None

    async def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Create or initialize one session metadata record."""
        return dict(metadata or {})

    async def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        """Update one session metadata record."""
        return None


class InMemorySessionStore(SessionStore):
    """Simple in-memory session store."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[Message]] = {}
        self._metadata: dict[str, dict[str, object]] = {}

    def load_history(self, session_id: str) -> list[Message]:
        history = self._sessions.get(session_id, [])
        return [dict(item) for item in history]

    def save_history(self, session_id: str, history: list[Message]) -> None:
        self._sessions[session_id] = [dict(item) for item in history]
        now = _utc_timestamp()
        metadata = self._metadata.get(session_id)
        if metadata is None:
            metadata = {
                "session_id": session_id,
                "created_at": now,
            }
            self._metadata[session_id] = metadata
        metadata["updated_at"] = now

    def delete_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._metadata.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        return sorted(set(self._sessions.keys()) | set(self._metadata.keys()))

    def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        metadata = self._metadata.get(session_id)
        return dict(metadata) if metadata is not None else None

    def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        existing = dict(self._metadata.get(session_id, {}))
        payload = dict(metadata or {})
        existing.setdefault("session_id", session_id)
        existing.setdefault("created_at", _utc_timestamp())
        existing.setdefault("updated_at", existing["created_at"])
        existing.update(payload)
        self._metadata[session_id] = existing
        return dict(existing)

    def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        existing = self._metadata.get(session_id)
        if existing is None:
            return None
        existing.update(metadata)
        existing["updated_at"] = _utc_timestamp()
        return dict(existing)


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

    def _meta_path_for(self, session_id: str) -> Path:
        return self.root_dir / f"{self._safe_name(session_id)}.meta.json"

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
        self._save_metadata(session_id)

    def delete_session(self, session_id: str) -> None:
        path = self._path_for(session_id)
        if path.exists():
            path.unlink()
        meta_path = self._meta_path_for(session_id)
        if meta_path.exists():
            meta_path.unlink()

    def list_sessions(self) -> list[str]:
        names: set[str] = set()
        for item in self.root_dir.glob("*.jsonl"):
            if not item.is_file():
                continue
            session_id = self._session_id_from_meta(item) or item.stem
            names.add(session_id)
        for item in self.root_dir.glob("*.meta.json"):
            if not item.is_file():
                continue
            session_id = self._session_id_from_meta_file(item)
            if session_id:
                names.add(session_id)
        return sorted(names)

    def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        meta_path = self._meta_path_for(session_id)
        if meta_path.exists():
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                payload = None
            if isinstance(payload, dict):
                metadata = dict(payload)
                metadata.setdefault("session_id", session_id)
                return metadata
        path = self._path_for(session_id)
        if not path.exists():
            return None
        fallback = _file_timestamp_metadata(path, session_id=session_id)
        return fallback

    def _save_metadata(self, session_id: str) -> None:
        meta_path = self._meta_path_for(session_id)
        existing = self.get_session_metadata(session_id) or {"session_id": session_id}
        if "created_at" not in existing:
            existing["created_at"] = _utc_timestamp()
        existing["updated_at"] = _utc_timestamp()
        meta_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _session_id_from_meta(self, path: Path) -> str | None:
        meta_path = path.with_suffix(".meta.json")
        return self._session_id_from_meta_file(meta_path)

    def _session_id_from_meta_file(self, meta_path: Path) -> str | None:
        if not meta_path.exists():
            return None
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if isinstance(payload, dict) and isinstance(payload.get("session_id"), str):
            return str(payload["session_id"])
        return None

    def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        meta_path = self._meta_path_for(session_id)
        existing = self.get_session_metadata(session_id) or {"session_id": session_id}
        now = _utc_timestamp()
        existing.setdefault("created_at", now)
        existing.setdefault("updated_at", now)
        existing.update(metadata or {})
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return dict(existing)

    def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        existing = self.get_session_metadata(session_id)
        if existing is None:
            return None
        existing.update(metadata)
        existing["updated_at"] = _utc_timestamp()
        self._meta_path_for(session_id).write_text(
            json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return existing


class SQLiteSessionStore(SessionStore):
    """SQLite-backed session store."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        from simplified_chatbot.runtime.sqlite_pragmas import apply_pragmas_sync

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        # WAL + tuned synchronous/cache_size — see sqlite_pragmas docstring for
        # the rationale. Sync store is mostly used by tests these days, but
        # keeping pragmas consistent avoids surprises if it's wired back in.
        apply_pragmas_sync(conn)
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_metadata (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT,
                    updated_at TEXT,
                    title TEXT
                )
                """,
            )
            columns = [
                str(row[1])
                for row in conn.execute("PRAGMA table_info(session_metadata)").fetchall()
            ]
            if "title" not in columns:
                conn.execute("ALTER TABLE session_metadata ADD COLUMN title TEXT")

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
        now = _utc_timestamp()
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
            conn.execute(
                """
                INSERT INTO session_metadata (session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (session_id, now, now),
            )
            conn.commit()

    def delete_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            conn.execute(
                "DELETE FROM session_metadata WHERE session_id = ?",
                (session_id,),
            )

    def list_sessions(self) -> list[str]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT session_id
                FROM session_metadata
                ORDER BY session_id ASC
                """,
            )
            rows = cursor.fetchall()
        return [str(session_id) for (session_id,) in rows]

    def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT created_at, updated_at, title
                FROM session_metadata
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        created_at, updated_at, title = row
        return {
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "title": title,
        }

    def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload = dict(metadata or {})
        now = _utc_timestamp()
        title = payload.get("title")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO session_metadata (session_id, created_at, updated_at, title)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, now, now, title if isinstance(title, str) else None),
            )
        existing = self.get_session_metadata(session_id) or {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
        }
        if payload:
            updated = self.update_session_metadata(session_id, payload)
            if updated is not None:
                return updated
        return existing

    def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        existing = self.get_session_metadata(session_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(metadata)
        merged["updated_at"] = _utc_timestamp()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE session_metadata
                SET title = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    merged.get("title") if isinstance(merged.get("title"), str) else None,
                    merged["updated_at"],
                    session_id,
                ),
            )
        return merged


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
            async with open_async(self.db_path) as conn:
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
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_metadata (
                        session_id TEXT PRIMARY KEY,
                        created_at TEXT,
                        updated_at TEXT,
                        title TEXT
                    )
                    """,
                )
                cursor = await conn.execute("PRAGMA table_info(session_metadata)")
                columns = [str(row[1]) for row in await cursor.fetchall()]
                await cursor.close()
                if "title" not in columns:
                    await conn.execute("ALTER TABLE session_metadata ADD COLUMN title TEXT")
                await conn.commit()
            self._initialized = True

    async def load_history(self, session_id: str) -> list[Message]:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
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
        now = _utc_timestamp()
        async with open_async(self.db_path) as conn:
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
            await conn.execute(
                """
                INSERT INTO session_metadata (session_id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at
                """,
                (session_id, now, now),
            )
            await conn.commit()

    async def delete_session(self, session_id: str) -> None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            await conn.execute(
                "DELETE FROM session_messages WHERE session_id = ?",
                (session_id,),
            )
            await conn.execute(
                "DELETE FROM session_metadata WHERE session_id = ?",
                (session_id,),
            )
            await conn.commit()

    async def list_sessions(self) -> list[str]:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id
                FROM session_metadata
                ORDER BY session_id ASC
                """,
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [str(session_id) for (session_id,) in rows]

    async def get_session_metadata(self, session_id: str) -> dict[str, object] | None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT created_at, updated_at, title
                FROM session_metadata
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        created_at, updated_at, title = row
        return {
            "session_id": session_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "title": title,
        }

    async def create_session(
        self,
        session_id: str,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        await self._ensure_initialized()
        payload = dict(metadata or {})
        now = _utc_timestamp()
        title = payload.get("title")
        async with open_async(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO session_metadata (session_id, created_at, updated_at, title)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO NOTHING
                """,
                (session_id, now, now, title if isinstance(title, str) else None),
            )
            await conn.commit()
        existing = await self.get_session_metadata(session_id) or {
            "session_id": session_id,
            "created_at": now,
            "updated_at": now,
        }
        if payload:
            updated = await self.update_session_metadata(session_id, payload)
            if updated is not None:
                return updated
        return existing

    async def update_session_metadata(
        self,
        session_id: str,
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        await self._ensure_initialized()
        existing = await self.get_session_metadata(session_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(metadata)
        merged["updated_at"] = _utc_timestamp()
        async with open_async(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE session_metadata
                SET title = ?, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    merged.get("title") if isinstance(merged.get("title"), str) else None,
                    merged["updated_at"],
                    session_id,
                ),
            )
            await conn.commit()
        return merged


class AioSQLiteSessionMemoryStore:
    """Async SQLite-backed store for rolling summaries and user memory notes."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "AioSQLiteSessionMemoryStore requires 'aiosqlite'. Install with: pip install aiosqlite",
            )
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._init_lock: Any = None

    async def ensure_schema(self) -> None:
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            import asyncio

            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            async with open_async(self.db_path) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_memory (
                        session_id TEXT PRIMARY KEY,
                        summary TEXT NOT NULL DEFAULT '',
                        compacted_message_count INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL
                    )
                    """,
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS session_memory_notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'note',
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        archived_at TEXT
                    )
                    """,
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_session_memory_notes_session
                    ON session_memory_notes(session_id, archived_at, updated_at DESC)
                    """,
                )
                await conn.commit()
            self._initialized = True

    async def load_memory(self, session_id: str) -> SessionMemoryRow | None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT session_id, summary, compacted_message_count, updated_at
                FROM session_memory
                WHERE session_id = ?
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return SessionMemoryRow(
            session_id=str(row[0]),
            summary=str(row[1] or ""),
            compacted_message_count=max(0, int(row[2] or 0)),
            updated_at=str(row[3] or ""),
        )

    async def save_memory(
        self,
        session_id: str,
        *,
        summary: str,
        compacted_message_count: int,
    ) -> SessionMemoryRow:
        await self._ensure_initialized()
        now = _utc_timestamp()
        compacted = max(0, int(compacted_message_count))
        async with open_async(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO session_memory (
                    session_id, summary, compacted_message_count, updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    summary = excluded.summary,
                    compacted_message_count = excluded.compacted_message_count,
                    updated_at = excluded.updated_at
                """,
                (session_id, summary, compacted, now),
            )
            await conn.commit()
        return SessionMemoryRow(
            session_id=session_id,
            summary=summary,
            compacted_message_count=compacted,
            updated_at=now,
        )

    async def delete_memory(self, session_id: str) -> None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            await conn.execute(
                "DELETE FROM session_memory WHERE session_id = ?",
                (session_id,),
            )
            await conn.commit()

    async def clear_summary(self, session_id: str) -> None:
        await self.delete_memory(session_id)

    async def list_notes(
        self,
        session_id: str,
        *,
        include_archived: bool = False,
    ) -> list[SessionMemoryNoteRow]:
        await self._ensure_initialized()
        query = [
            """
            SELECT id, session_id, kind, content, created_at, updated_at, archived_at
            FROM session_memory_notes
            WHERE session_id = ?
            """
        ]
        params: list[object] = [session_id]
        if not include_archived:
            query.append("AND archived_at IS NULL")
        query.append("ORDER BY updated_at DESC, id DESC")
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute("\n".join(query), tuple(params))
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._note_from_row(row) for row in rows]

    async def add_note(
        self,
        session_id: str,
        *,
        content: str,
        kind: str = "note",
    ) -> SessionMemoryNoteRow:
        await self._ensure_initialized()
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("memory note content must not be empty")
        normalized_kind = kind.strip() or "note"
        now = _utc_timestamp()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO session_memory_notes (
                    session_id, kind, content, created_at, updated_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (session_id, normalized_kind, cleaned, now, now),
            )
            await conn.commit()
            note_id = int(cursor.lastrowid)
            await cursor.close()
        return SessionMemoryNoteRow(
            id=note_id,
            session_id=session_id,
            kind=normalized_kind,
            content=cleaned,
            created_at=now,
            updated_at=now,
            archived_at=None,
        )

    async def archive_note(
        self,
        session_id: str,
        note_id: int,
    ) -> SessionMemoryNoteRow | None:
        await self._ensure_initialized()
        now = _utc_timestamp()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                UPDATE session_memory_notes
                SET archived_at = ?, updated_at = ?
                WHERE session_id = ? AND id = ? AND archived_at IS NULL
                """,
                (now, now, session_id, note_id),
            )
            updated = cursor.rowcount
            await cursor.close()
            await conn.commit()
        if not updated:
            return None
        return await self.get_note(session_id, note_id, include_archived=True)

    async def get_note(
        self,
        session_id: str,
        note_id: int,
        *,
        include_archived: bool = False,
    ) -> SessionMemoryNoteRow | None:
        await self._ensure_initialized()
        query = [
            """
            SELECT id, session_id, kind, content, created_at, updated_at, archived_at
            FROM session_memory_notes
            WHERE session_id = ? AND id = ?
            """
        ]
        params: list[object] = [session_id, note_id]
        if not include_archived:
            query.append("AND archived_at IS NULL")
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute("\n".join(query), tuple(params))
            row = await cursor.fetchone()
            await cursor.close()
        return self._note_from_row(row) if row is not None else None

    async def delete_session_data(self, session_id: str) -> None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            await conn.execute(
                "DELETE FROM session_memory WHERE session_id = ?",
                (session_id,),
            )
            await conn.execute(
                "DELETE FROM session_memory_notes WHERE session_id = ?",
                (session_id,),
            )
            await conn.commit()

    @staticmethod
    def _note_from_row(row: tuple[object, ...]) -> SessionMemoryNoteRow:
        return SessionMemoryNoteRow(
            id=int(row[0]),
            session_id=str(row[1]),
            kind=str(row[2] or "note"),
            content=str(row[3] or ""),
            created_at=str(row[4] or ""),
            updated_at=str(row[5] or ""),
            archived_at=str(row[6]) if isinstance(row[6], str) else None,
        )


class AioSQLiteSubagentStore:
    """Async SQLite-backed store for persisted subagent runs."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "AioSQLiteSubagentStore requires 'aiosqlite'. Install with: pip install aiosqlite",
            )
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._init_lock: Any = None

    async def ensure_schema(self) -> None:
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            import asyncio

            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            async with open_async(self.db_path) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subagent_runs (
                        task_id TEXT PRIMARY KEY,
                        parent_session_id TEXT NOT NULL,
                        label TEXT NOT NULL,
                        task TEXT NOT NULL,
                        workspace TEXT,
                        phase TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        stop_reason TEXT,
                        ok INTEGER,
                        error TEXT,
                        usage_json TEXT NOT NULL,
                        tool_events_json TEXT NOT NULL,
                        final_content TEXT,
                        model TEXT
                    )
                    """,
                )
                cursor = await conn.execute("PRAGMA table_info(subagent_runs)")
                existing_columns = {row[1] for row in await cursor.fetchall()}
                await cursor.close()
                if "model" not in existing_columns:
                    await conn.execute(
                        "ALTER TABLE subagent_runs ADD COLUMN model TEXT",
                    )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_subagent_runs_parent_session
                    ON subagent_runs(parent_session_id, started_at DESC)
                    """,
                )
                await conn.commit()
            self._initialized = True

    async def upsert_run(self, payload: dict[str, object]) -> None:
        await self._ensure_initialized()
        row = self._normalize_payload(payload)
        async with open_async(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO subagent_runs (
                    task_id,
                    parent_session_id,
                    label,
                    task,
                    workspace,
                    phase,
                    started_at,
                    finished_at,
                    stop_reason,
                    ok,
                    error,
                    usage_json,
                    tool_events_json,
                    final_content,
                    model
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    parent_session_id = excluded.parent_session_id,
                    label = excluded.label,
                    task = excluded.task,
                    workspace = excluded.workspace,
                    phase = excluded.phase,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    stop_reason = excluded.stop_reason,
                    ok = excluded.ok,
                    error = excluded.error,
                    usage_json = excluded.usage_json,
                    tool_events_json = excluded.tool_events_json,
                    final_content = excluded.final_content,
                    model = COALESCE(excluded.model, subagent_runs.model)
                """,
                row,
            )
            await conn.commit()

    async def get_run(self, task_id: str) -> dict[str, object] | None:
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT
                    task_id,
                    parent_session_id,
                    label,
                    task,
                    workspace,
                    phase,
                    started_at,
                    finished_at,
                    stop_reason,
                    ok,
                    error,
                    usage_json,
                    tool_events_json,
                    final_content,
                    model
                FROM subagent_runs
                WHERE task_id = ?
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return self._row_to_payload(row) if row is not None else None

    async def list_runs(
        self,
        *,
        parent_session_id: str | None = None,
        phase: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        await self._ensure_initialized()
        query = [
            """
            SELECT
                task_id,
                parent_session_id,
                label,
                task,
                workspace,
                phase,
                started_at,
                finished_at,
                stop_reason,
                ok,
                error,
                usage_json,
                tool_events_json,
                final_content,
                model
            FROM subagent_runs
            """
        ]
        clauses: list[str] = []
        params: list[object] = []
        if parent_session_id is not None:
            clauses.append("parent_session_id = ?")
            params.append(parent_session_id)
        if phase is not None:
            clauses.append("phase = ?")
            params.append(phase)
        if clauses:
            query.append("WHERE " + " AND ".join(clauses))
        query.append("ORDER BY started_at DESC")
        query.append("LIMIT ?")
        params.append(limit)

        async with open_async(self.db_path) as conn:
            cursor = await conn.execute("\n".join(query), tuple(params))
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._row_to_payload(row) for row in rows]

    @staticmethod
    def _normalize_payload(payload: dict[str, object]) -> tuple[object, ...]:
        task_id = str(payload["task_id"])
        parent_session_id = str(payload["parent_session_id"])
        label = str(payload["label"])
        task = str(payload["task"])
        workspace = payload.get("workspace")
        phase = str(payload["phase"])
        started_at = str(payload["started_at"])
        finished_at = payload.get("finished_at")
        stop_reason = payload.get("stop_reason")
        ok = payload.get("ok")
        error = payload.get("error")
        usage = payload.get("usage", {})
        tool_events = payload.get("tool_events", [])
        final_content = payload.get("final_content")
        model = payload.get("model")

        return (
            task_id,
            parent_session_id,
            label,
            task,
            str(workspace) if isinstance(workspace, (str, Path)) else None,
            phase,
            started_at,
            str(finished_at) if isinstance(finished_at, str) else None,
            str(stop_reason) if isinstance(stop_reason, str) else None,
            _bool_to_sqlite(ok),
            str(error) if isinstance(error, str) else None,
            json.dumps(usage if isinstance(usage, dict) else {}, ensure_ascii=False),
            json.dumps(tool_events if isinstance(tool_events, list) else [], ensure_ascii=False),
            str(final_content) if isinstance(final_content, str) else None,
            str(model) if isinstance(model, str) and model else None,
        )

    @staticmethod
    def _row_to_payload(row: tuple[object, ...]) -> dict[str, object]:
        (
            task_id,
            parent_session_id,
            label,
            task,
            workspace,
            phase,
            started_at,
            finished_at,
            stop_reason,
            ok,
            error,
            usage_json,
            tool_events_json,
            final_content,
            model,
        ) = row
        return {
            "task_id": str(task_id),
            "parent_session_id": str(parent_session_id),
            "label": str(label),
            "task": str(task),
            "workspace": str(workspace) if isinstance(workspace, str) else None,
            "phase": str(phase),
            "started_at": str(started_at),
            "finished_at": str(finished_at) if isinstance(finished_at, str) else None,
            "stop_reason": str(stop_reason) if isinstance(stop_reason, str) else None,
            "ok": _sqlite_to_bool(ok),
            "error": str(error) if isinstance(error, str) else None,
            "usage": _safe_load_json_dict(usage_json),
            "tool_events": _safe_load_json_list(tool_events_json),
            "final_content": str(final_content) if isinstance(final_content, str) else None,
            "model": str(model) if isinstance(model, str) and model else None,
        }


class AioSQLiteSubagentEventStore:
    """Async SQLite-backed append-only event store for subagent timelines."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "AioSQLiteSubagentEventStore requires 'aiosqlite'. Install with: pip install aiosqlite",
            )
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialized = False
        self._init_lock: Any = None

    async def ensure_schema(self) -> None:
        await self._ensure_initialized()

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._init_lock is None:
            import asyncio

            self._init_lock = asyncio.Lock()
        async with self._init_lock:
            if self._initialized:
                return
            async with open_async(self.db_path) as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subagent_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        parent_session_id TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """,
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_subagent_events_task_seq
                    ON subagent_events(task_id, seq)
                    """,
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_subagent_events_parent_session
                    ON subagent_events(parent_session_id, created_at)
                    """,
                )
                await conn.commit()
            self._initialized = True

    async def append_event(
        self,
        *,
        task_id: str,
        parent_session_id: str,
        event_type: str,
        payload: dict[str, object],
        created_at: str | None = None,
    ) -> dict[str, object]:
        await self._ensure_initialized()
        created = created_at or _utc_timestamp()
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with open_async(self.db_path) as conn:
            await conn.execute("BEGIN IMMEDIATE")
            cursor = await conn.execute(
                """
                SELECT COALESCE(MAX(seq), 0)
                FROM subagent_events
                WHERE task_id = ?
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
            next_seq = int(row[0]) + 1 if row is not None else 1
            insert = await conn.execute(
                """
                INSERT INTO subagent_events (
                    task_id,
                    parent_session_id,
                    seq,
                    event_type,
                    created_at,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    parent_session_id,
                    next_seq,
                    event_type,
                    created,
                    payload_json,
                ),
            )
            await conn.commit()
            event_id = int(insert.lastrowid)
        return {
            "id": event_id,
            "task_id": task_id,
            "parent_session_id": parent_session_id,
            "seq": next_seq,
            "event_type": event_type,
            "created_at": created,
            "payload": dict(payload),
        }

    async def list_events(
        self,
        task_id: str,
        *,
        parent_session_id: str | None = None,
        after_seq: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        await self._ensure_initialized()
        query = [
            """
            SELECT
                id,
                task_id,
                parent_session_id,
                seq,
                event_type,
                created_at,
                payload_json
            FROM subagent_events
            WHERE task_id = ?
            """
        ]
        params: list[object] = [task_id]
        if parent_session_id is not None:
            query.append("AND parent_session_id = ?")
            params.append(parent_session_id)
        if after_seq is not None:
            query.append("AND seq > ?")
            params.append(after_seq)
        query.append("ORDER BY seq ASC")
        query.append("LIMIT ?")
        params.append(limit)
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute("\n".join(query), tuple(params))
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._row_to_payload(row) for row in rows]

    @staticmethod
    def _row_to_payload(row: tuple[object, ...]) -> dict[str, object]:
        event_id, task_id, parent_session_id, seq, event_type, created_at, payload_json = row
        return {
            "id": int(event_id),
            "task_id": str(task_id),
            "parent_session_id": str(parent_session_id),
            "seq": int(seq),
            "event_type": str(event_type),
            "created_at": str(created_at),
            "payload": _safe_load_json_dict(payload_json),
        }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _file_timestamp_metadata(path: Path, *, session_id: str) -> dict[str, object]:
    updated = datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    return {
        "session_id": session_id,
        "created_at": updated,
        "updated_at": updated,
    }


def _bool_to_sqlite(value: object) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _sqlite_to_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _safe_load_json_dict(payload: object) -> dict[str, object]:
    if not isinstance(payload, str):
        return {}
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _safe_load_json_list(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, str):
        return []
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]
