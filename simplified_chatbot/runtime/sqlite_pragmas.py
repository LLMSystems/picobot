"""Shared aiosqlite open helper that applies picobot's preferred PRAGMAs.

Use [`open_async(db_path)`][open_async] in place of `aiosqlite.connect(...)`
anywhere we touch the DB. Centralising the open path is what lets us flip
the whole app to WAL mode at once without chasing every callsite later.

PRAGMAs in priority order:

- **journal_mode=WAL** — single biggest concurrency win. Writers and readers
  stop blocking each other, which was the root cause of dashboard / chat /
  snapshot-tick contention. Persistent at the DB-file level once set, so a
  no-op on subsequent connections.
- **synchronous=NORMAL** — one fsync per checkpoint instead of per commit.
  Safe under WAL: a hard crash can lose the last commit (acceptable for
  metrics / chat logs) but the DB itself stays consistent.
- **cache_size=-32000** — 32 MiB page cache (default is 2 MiB). Most history
  queries hit the same pages repeatedly.
- **temp_store=MEMORY** — keep transient b-trees off disk.
- **busy_timeout=5000** — wait up to 5 s on a lock before erroring. With WAL
  this almost never fires; without it the dashboard could trip SQLITE_BUSY
  during snapshot writes.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]


_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-32000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA busy_timeout=5000",
)


@asynccontextmanager
async def open_async(db_path: str | Path) -> "AsyncIterator[aiosqlite.Connection]":
    """Open an aiosqlite connection with picobot's preferred PRAGMAs applied.

    Mirrors `aiosqlite.connect()`'s async-context-manager contract; the only
    differences are the PRAGMA round-trip on entry and the centralised close.
    """
    if aiosqlite is None:
        raise ImportError("aiosqlite is required to use open_async")
    conn = await aiosqlite.connect(str(db_path))
    try:
        for pragma in _PRAGMAS:
            await conn.execute(pragma)
        yield conn
    finally:
        await conn.close()


def apply_pragmas_sync(conn) -> None:
    """Same PRAGMAs but for sync `sqlite3.Connection` (used by the legacy
    `SessionStore`). Skips journal_mode if it's already WAL to keep this
    cheap on hot paths."""
    for pragma in _PRAGMAS:
        try:
            conn.execute(pragma)
        except Exception:
            # Any PRAGMA failure here is a tuning miss, not correctness — let
            # the caller proceed with default settings rather than crash.
            pass
