"""Shared read/write state for filesystem tools."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ReadState:
    mtime: float
    offset: int
    limit: int | None
    content_hash: str | None
    can_dedup: bool


def _hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


class FileStates:
    """Track read/write freshness for read dedup and read-before-edit warnings."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state: dict[str, ReadState] = {}

    def record_read(self, path: str | Path, offset: int = 1, limit: int | None = None) -> None:
        resolved = Path(path).resolve()
        try:
            mtime = os.path.getmtime(resolved)
        except OSError:
            return
        self._state[str(resolved)] = ReadState(
            mtime=mtime,
            offset=offset,
            limit=limit,
            content_hash=_hash_file(resolved),
            can_dedup=True,
        )

    def record_write(self, path: str | Path) -> None:
        resolved = Path(path).resolve()
        try:
            mtime = os.path.getmtime(resolved)
        except OSError:
            self._state.pop(str(resolved), None)
            return
        self._state[str(resolved)] = ReadState(
            mtime=mtime,
            offset=1,
            limit=None,
            content_hash=_hash_file(resolved),
            can_dedup=False,
        )

    def check_read(self, path: str | Path) -> str | None:
        """Return warning text when edit is stale/unsafe, otherwise None."""
        resolved = Path(path).resolve()
        key = str(resolved)
        entry = self._state.get(key)
        if entry is None:
            return (
                "Warning: file has not been read yet. "
                "Read it first to verify content before editing."
            )
        try:
            current_mtime = os.path.getmtime(resolved)
        except OSError:
            return None

        if current_mtime != entry.mtime:
            current_hash = _hash_file(resolved)
            if current_hash == entry.content_hash:
                entry.mtime = current_mtime
                return None
            return (
                "Warning: file has been modified since last read. "
                "Re-read to verify content before editing."
            )

        if entry.content_hash and _hash_file(resolved) != entry.content_hash:
            return (
                "Warning: file has been modified since last read. "
                "Re-read to verify content before editing."
            )
        return None

    def is_unchanged(self, path: str | Path, offset: int = 1, limit: int | None = None) -> bool:
        resolved = Path(path).resolve()
        key = str(resolved)
        entry = self._state.get(key)
        if entry is None or not entry.can_dedup:
            return False
        if entry.offset != offset or entry.limit != limit:
            return False

        try:
            current_mtime = os.path.getmtime(resolved)
        except OSError:
            return False
        if current_mtime != entry.mtime:
            if _hash_file(resolved) == entry.content_hash:
                entry.mtime = current_mtime
                return True
            entry.can_dedup = False
            return False
        if entry.content_hash and _hash_file(resolved) != entry.content_hash:
            entry.can_dedup = False
            return False
        return True

    def clear(self) -> None:
        self._state.clear()

