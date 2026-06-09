"""AioSQLite-backed user store.

Mirrors the structure of [AioSQLiteSessionStore][simplified_chatbot.runtime.session_store]
— same `open_async` helper, same lazy `_ensure_initialized` lock — so users live
in the same SQLite file as sessions and pick up the shared WAL pragmas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import aiosqlite  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.auth.passwords import hash_password, verify_password
from simplified_chatbot.runtime.sqlite_pragmas import open_async


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class User:
    """One registered user (never carries the password hash to callers)."""

    id: int
    username: str
    created_at: str


class UsernameTakenError(ValueError):
    """Raised when registering a username that already exists."""


class UsersStore:
    """Persist and authenticate users in SQLite."""

    def __init__(self, db_path: str | Path) -> None:
        if aiosqlite is None:
            raise ImportError(
                "UsersStore requires 'aiosqlite'. Install with: pip install aiosqlite",
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
                    CREATE TABLE IF NOT EXISTS users (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        username      TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        created_at    TEXT NOT NULL
                    )
                    """,
                )
                # Case-insensitive uniqueness: store normalized username, but a
                # functional unique index makes the DB the source of truth even
                # if a caller forgets to normalize.
                await conn.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_nocase
                    ON users(username COLLATE NOCASE)
                    """,
                )
                await conn.commit()
            self._initialized = True

    @staticmethod
    def _normalize_username(username: str) -> str:
        return username.strip().lower()

    async def create_user(self, username: str, password: str) -> User:
        """Register a new user. Raises UsernameTakenError / WeakPasswordError."""
        await self._ensure_initialized()
        normalized = self._normalize_username(username)
        if not normalized:
            raise ValueError("Username must not be empty")
        # hash_password validates strength before we touch the DB.
        password_hash = hash_password(password)
        now = _utc_timestamp()
        async with open_async(self.db_path) as conn:
            existing = await conn.execute(
                "SELECT 1 FROM users WHERE username = ? COLLATE NOCASE",
                (normalized,),
            )
            if await existing.fetchone() is not None:
                await existing.close()
                raise UsernameTakenError(f"Username '{username}' is already taken")
            await existing.close()
            cursor = await conn.execute(
                """
                INSERT INTO users (username, password_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (normalized, password_hash, now),
            )
            await conn.commit()
            user_id = int(cursor.lastrowid)
            await cursor.close()
        return User(id=user_id, username=normalized, created_at=now)

    async def get_by_id(self, user_id: int) -> User | None:
        """Look up a user by id (used to resolve the cookie's user_id)."""
        await self._ensure_initialized()
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT id, username, created_at FROM users WHERE id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        return User(id=int(row[0]), username=str(row[1]), created_at=str(row[2]))

    async def authenticate(self, username: str, password: str) -> User | None:
        """Return the user iff credentials are valid, else None (no enumeration)."""
        await self._ensure_initialized()
        normalized = self._normalize_username(username)
        async with open_async(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, username, password_hash, created_at
                FROM users WHERE username = ? COLLATE NOCASE
                """,
                (normalized,),
            )
            row = await cursor.fetchone()
            await cursor.close()
        if row is None:
            return None
        if not verify_password(str(row[2]), password):
            return None
        return User(id=int(row[0]), username=str(row[1]), created_at=str(row[3]))
