"""Session history stores for local runtime."""

from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
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
        now = _utc_timestamp()
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
            async with aiosqlite.connect(str(self.db_path)) as conn:
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
                        final_content TEXT
                    )
                    """,
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
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
                    final_content
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    final_content = excluded.final_content
                """,
                row,
            )
            await conn.commit()

    async def get_run(self, task_id: str) -> dict[str, object] | None:
        await self._ensure_initialized()
        async with aiosqlite.connect(str(self.db_path)) as conn:
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
                    final_content
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
                final_content
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

        async with aiosqlite.connect(str(self.db_path)) as conn:
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
