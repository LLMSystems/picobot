"""Workspace disk-usage collector with a 5-minute internal cache."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic


@dataclass
class WorkspaceSample:
    total_bytes: int | None
    session_count: int | None
    per_session_bytes: dict[str, int]
    measured_at: float | None  # monotonic seconds


class WorkspaceCollector:
    """Sample on-disk workspace usage.

    `collect()` always returns instantly, serving the last cached sample.
    A traversal is launched lazily when the cache is older than `cache_ttl`.
    """

    def __init__(
        self,
        workspace_root_dir: str | Path | None,
        *,
        cache_ttl: float = 300.0,
    ) -> None:
        self._root: Path | None = (
            Path(workspace_root_dir).expanduser().resolve()
            if workspace_root_dir
            else None
        )
        self._cache_ttl = cache_ttl
        self._cache: WorkspaceSample = WorkspaceSample(
            total_bytes=None,
            session_count=None,
            per_session_bytes={},
            measured_at=None,
        )
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None

    async def collect(self) -> WorkspaceSample:
        if self._root is None or not self._root.exists():
            return WorkspaceSample(
                total_bytes=None,
                session_count=None,
                per_session_bytes={},
                measured_at=None,
            )
        if self._needs_refresh():
            await self._ensure_refresh()
        return self._cache

    def _needs_refresh(self) -> bool:
        if self._cache.measured_at is None:
            return True
        return (monotonic() - self._cache.measured_at) >= self._cache_ttl

    async def _ensure_refresh(self) -> None:
        # Coalesce concurrent refreshes; let the first one win and others wait.
        if self._refresh_task is not None and not self._refresh_task.done():
            await self._refresh_task
            return
        async with self._refresh_lock:
            if not self._needs_refresh():
                return
            self._refresh_task = asyncio.create_task(self._refresh())
        await self._refresh_task

    async def _refresh(self) -> None:
        assert self._root is not None
        sample = await asyncio.to_thread(_traverse, self._root)
        self._cache = sample

    def session_bytes(self, session_id: str) -> int | None:
        return self._cache.per_session_bytes.get(session_id)

    @property
    def measured_at(self) -> float | None:
        return self._cache.measured_at


def _traverse(root: Path) -> WorkspaceSample:
    total = 0
    per_session: dict[str, int] = {}
    try:
        children = list(root.iterdir())
    except OSError:
        return WorkspaceSample(
            total_bytes=0,
            session_count=0,
            per_session_bytes={},
            measured_at=monotonic(),
        )
    for child in children:
        if not child.is_dir():
            continue
        session_total = _dir_size(child)
        per_session[child.name] = session_total
        total += session_total
    return WorkspaceSample(
        total_bytes=total,
        session_count=len(per_session),
        per_session_bytes=per_session,
        measured_at=monotonic(),
    )


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total
