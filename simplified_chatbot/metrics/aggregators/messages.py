"""Aggregators that derive tool, iteration, and message stats from session_messages.

`session_messages.payload` is a JSON-encoded Message dict. We stream rows row by
row to keep memory bounded even for large transcripts.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

try:
    import aiosqlite  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - aiosqlite ships in pyproject
    aiosqlite = None  # type: ignore[assignment]

from simplified_chatbot.runtime.sqlite_pragmas import open_async


@dataclass
class ToolBreakdownEntry:
    name: str
    count: int
    success: int
    failure: int

    @property
    def success_rate(self) -> float:
        seen = self.success + self.failure
        return self.success / seen if seen > 0 else 1.0


@dataclass
class MessageAggregate:
    message_count: int = 0
    assistant_turns: int = 0
    tool_calls_total: int = 0
    tool_success_total: int = 0
    tool_failure_total: int = 0
    tools_by_name: dict[str, ToolBreakdownEntry] = field(default_factory=dict)

    @property
    def tool_success_rate(self) -> float:
        seen = self.tool_success_total + self.tool_failure_total
        return self.tool_success_total / seen if seen > 0 else 1.0


# Cap the number of session_messages rows we scan per aggregate. Used to be a
# full table scan — fine at a few hundred rows but degrades linearly as the DB
# grows, and this runs every 10 s on the snapshot tick. The cap turns the
# global aggregate into a rolling "recent N messages" stat: older tool calls
# fall out of the success-rate window, which is the right behaviour for a
# dashboard anyway. Bump if you need a deeper retrospective.
_DEFAULT_ROW_LIMIT = 10_000


async def aggregate_messages(
    db_path: str | Path | None,
    *,
    session_id: str | None = None,
    row_limit: int = _DEFAULT_ROW_LIMIT,
) -> MessageAggregate:
    """Aggregate tool / iteration stats either globally or for one session.

    Only one pass per row; we recognise tool results by the conventional
    `tool` role with `tool_call_id`. The result's `ok` flag is best-effort —
    when missing we count the call as success.

    Caps at `row_limit` rows (newest-first) to bound snapshot-tick latency.
    The inner subquery selects the most recent N by rowid, then we re-sort
    chronologically so the tool_call → tool_result pairing still works.
    """
    out = MessageAggregate()
    if db_path is None or aiosqlite is None:
        return out
    p = Path(db_path)
    if not p.exists():
        return out
    if session_id is None:
        sql = (
            "SELECT payload FROM ("
            "  SELECT rowid, payload FROM session_messages"
            "  ORDER BY rowid DESC LIMIT ?"
            ") ORDER BY rowid ASC"
        )
        params: tuple = (int(row_limit),)
    else:
        sql = (
            "SELECT payload FROM ("
            "  SELECT rowid, payload FROM session_messages"
            "  WHERE session_id = ?"
            "  ORDER BY rowid DESC LIMIT ?"
            ") ORDER BY rowid ASC"
        )
        params = (session_id, int(row_limit))
    try:
        conn_ctx = open_async(p)
    except Exception:
        return out
    async with conn_ctx as conn:
        try:
            cursor = await conn.execute(sql, params)
        except Exception:
            # DB exists but session_messages hasn't been created yet.
            return out
        tool_call_pending: dict[str, str] = {}
        async for (raw,) in cursor:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            out.message_count += 1
            role = msg.get("role")
            if role == "assistant":
                out.assistant_turns += 1
                tool_calls = msg.get("tool_calls") or []
                if isinstance(tool_calls, list):
                    for tc in tool_calls:
                        if not isinstance(tc, dict):
                            continue
                        name = _extract_tool_name(tc)
                        if not name:
                            continue
                        entry = out.tools_by_name.setdefault(
                            name,
                            ToolBreakdownEntry(name=name, count=0, success=0, failure=0),
                        )
                        entry.count += 1
                        out.tool_calls_total += 1
                        tc_id = tc.get("id")
                        if isinstance(tc_id, str):
                            tool_call_pending[tc_id] = name
            elif role == "tool":
                tc_id = msg.get("tool_call_id")
                if not isinstance(tc_id, str):
                    continue
                name = tool_call_pending.pop(tc_id, None) or msg.get("name")
                if not isinstance(name, str):
                    continue
                ok = _coerce_ok(msg)
                entry = out.tools_by_name.get(name)
                if entry is None:
                    # Tool result without a corresponding call seen yet — count
                    # the result so the success/failure totals stay coherent.
                    entry = ToolBreakdownEntry(name=name, count=0, success=0, failure=0)
                    out.tools_by_name[name] = entry
                if ok:
                    entry.success += 1
                    out.tool_success_total += 1
                else:
                    entry.failure += 1
                    out.tool_failure_total += 1
        await cursor.close()
    return out


def _extract_tool_name(tc: dict) -> str | None:
    fn = tc.get("function")
    if isinstance(fn, dict):
        name = fn.get("name")
        if isinstance(name, str) and name:
            return name
    direct = tc.get("name")
    if isinstance(direct, str) and direct:
        return direct
    return None


def _coerce_ok(msg: dict) -> bool:
    """Best-effort `ok` extraction from a tool-result message.

    Result payloads vary: some embed `{"ok": true}` JSON in `content`, others
    are plain strings. When ambiguous we treat the call as a success.
    """
    content = msg.get("content")
    if isinstance(content, str):
        stripped = content.lstrip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict) and "ok" in parsed:
                    return bool(parsed.get("ok"))
            except Exception:
                pass
        return True
    if isinstance(content, dict) and "ok" in content:
        return bool(content.get("ok"))
    return True
