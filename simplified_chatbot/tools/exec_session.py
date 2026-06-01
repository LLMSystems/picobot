"""Session support for long-running exec workflows."""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters


DEFAULT_YIELD_MS = 1000
MAX_YIELD_MS = 30_000
DEFAULT_MAX_OUTPUT_CHARS = 10_000
MAX_OUTPUT_CHARS = 50_000


@dataclass(slots=True)
class SessionPoll:
    output: str
    done: bool
    exit_code: int | None
    elapsed_s: float = 0.0
    timed_out: bool = False
    terminated: bool = False
    stdin_closed: bool = False
    truncated_chars: int = 0


@dataclass(slots=True)
class ExecSessionInfo:
    session_id: str
    owner_session_id: str | None
    command: str
    cwd: str
    elapsed_s: float
    idle_s: float
    remaining_s: float
    returncode: int | None


class _ExecSession:
    def __init__(
        self,
        *,
        session_id: str,
        owner_session_id: str | None,
        process: asyncio.subprocess.Process,
        command: str,
        cwd: str,
        timeout: int | None,
    ) -> None:
        self.session_id = session_id
        self.owner_session_id = owner_session_id
        self.process = process
        self.command = command
        self.cwd = cwd
        self.started_at = time.monotonic()
        self.last_access = time.monotonic()
        self.deadline = time.monotonic() + timeout if timeout else float("inf")
        self._chunks: list[str] = []
        self._lock = asyncio.Lock()
        self._timed_out = False
        self._stdout_task = asyncio.create_task(self._read_stream(process.stdout, ""))
        self._stderr_task = asyncio.create_task(self._read_stream(process.stderr, "STDERR:\n"))

    async def _read_stream(
        self,
        stream: asyncio.StreamReader | None,
        prefix: str,
    ) -> None:
        if stream is None:
            return
        first = True
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if prefix and first:
                text = prefix + text
                first = False
            async with self._lock:
                self._chunks.append(text)

    async def poll(
        self,
        yield_time_ms: int,
        max_output_chars: int,
        *,
        terminated: bool = False,
        stdin_closed: bool = False,
    ) -> SessionPoll:
        self.last_access = time.monotonic()
        if yield_time_ms > 0 and self.process.returncode is None:
            await asyncio.sleep(min(yield_time_ms, MAX_YIELD_MS) / 1000)

        if self.process.returncode is None and time.monotonic() >= self.deadline:
            self._timed_out = True
            await self.kill()

        if self.process.returncode is not None:
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.gather(self._stdout_task, self._stderr_task),
                    timeout=2.0,
                )

        async with self._lock:
            output = "".join(self._chunks)
            self._chunks.clear()

        output, truncated = truncate_output(output, max_output_chars)
        return SessionPoll(
            output=output,
            done=self.process.returncode is not None,
            exit_code=self.process.returncode,
            elapsed_s=max(0.0, time.monotonic() - self.started_at),
            timed_out=self._timed_out,
            terminated=terminated,
            stdin_closed=stdin_closed,
            truncated_chars=truncated,
        )

    async def write(self, chars: str) -> str | None:
        if self.process.returncode is not None:
            return "session has already exited"
        if self.process.stdin is None:
            return "session stdin is not available"
        try:
            self.process.stdin.write(chars.encode("utf-8"))
            await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            return "session stdin is closed"
        return None

    async def close_stdin(self) -> str | None:
        if self.process.returncode is not None:
            return "session has already exited"
        if self.process.stdin is None:
            return "session stdin is not available"
        self.process.stdin.close()
        with suppress(BrokenPipeError, ConnectionResetError):
            await self.process.stdin.wait_closed()
        return None

    async def kill(self) -> None:
        if self.process.returncode is not None:
            return
        self.process.kill()
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.process.wait(), timeout=5.0)


class ExecSessionManager:
    def __init__(self, *, max_sessions: int = 8, idle_timeout: int = 1800) -> None:
        self.max_sessions = max_sessions
        self.idle_timeout = idle_timeout
        self._sessions: dict[str, _ExecSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        *,
        command: str,
        cwd: str,
        env: dict[str, str],
        timeout: int | None,
        spawn: Any,
        owner_session_id: str | None,
        yield_time_ms: int,
        max_output_chars: int,
    ) -> tuple[str, SessionPoll]:
        async with self._lock:
            await self._cleanup_locked()
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(f"maximum exec sessions reached ({self.max_sessions})")
            process = await spawn(command, cwd, env)
            session_id = uuid.uuid4().hex[:12]
            session = _ExecSession(
                session_id=session_id,
                owner_session_id=owner_session_id,
                process=process,
                command=command,
                cwd=cwd,
                timeout=timeout,
            )
            self._sessions[session_id] = session

        poll = await session.poll(yield_time_ms, max_output_chars)
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return session_id, poll

    async def list(self, *, owner_session_id: str | None = None) -> list[ExecSessionInfo]:
        async with self._lock:
            await self._cleanup_locked()
            now = time.monotonic()
            return [
                ExecSessionInfo(
                    session_id=session_id,
                    owner_session_id=session.owner_session_id,
                    command=session.command,
                    cwd=session.cwd,
                    elapsed_s=max(0.0, now - session.started_at),
                    idle_s=max(0.0, now - session.last_access),
                    remaining_s=max(0.0, session.deadline - now),
                    returncode=session.process.returncode,
                )
                for session_id, session in sorted(self._sessions.items())
                if owner_session_id is None or session.owner_session_id == owner_session_id
            ]

    async def write(
        self,
        *,
        session_id: str,
        chars: str | None,
        close_stdin: bool,
        terminate: bool,
        owner_session_id: str | None = None,
        yield_time_ms: int,
        max_output_chars: int,
    ) -> SessionPoll:
        async with self._lock:
            await self._cleanup_locked()
            session = self._sessions.get(session_id)
        if session is None or not self._is_owner_allowed(session, owner_session_id):
            raise KeyError(session_id)

        if chars:
            error = await session.write(chars)
            if error:
                raise RuntimeError(error)
        stdin_closed = False
        if close_stdin:
            error = await session.close_stdin()
            if error:
                raise RuntimeError(error)
            stdin_closed = True
        if terminate:
            await session.kill()
        poll = await session.poll(
            yield_time_ms,
            max_output_chars,
            terminated=terminate,
            stdin_closed=stdin_closed,
        )
        if poll.done:
            async with self._lock:
                self._sessions.pop(session_id, None)
        return poll

    async def terminate_owner_sessions(self, owner_session_id: str) -> int:
        async with self._lock:
            await self._cleanup_locked()
            victims = [
                (session_id, session)
                for session_id, session in self._sessions.items()
                if session.owner_session_id == owner_session_id
            ]
            for session_id, _ in victims:
                self._sessions.pop(session_id, None)

        for _, session in victims:
            await session.kill()
        return len(victims)

    def terminate_owner_sessions_sync(self, owner_session_id: str) -> int:
        from simplified_chatbot.tools.registry import _DEFAULT_ASYNC_TOOL_RUNNER

        return _DEFAULT_ASYNC_TOOL_RUNNER.run(
            self.terminate_owner_sessions(owner_session_id),
        )

    @staticmethod
    def _is_owner_allowed(
        session: _ExecSession,
        owner_session_id: str | None,
    ) -> bool:
        return owner_session_id is None or session.owner_session_id == owner_session_id

    async def _cleanup_locked(self) -> None:
        now = time.monotonic()
        stale = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_access > self.idle_timeout
        ]
        for session_id in stale:
            session = self._sessions.pop(session_id)
            await session.kill()


DEFAULT_EXEC_SESSION_MANAGER = ExecSessionManager()


def clamp_session_int(value: int | None, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    return min(max(value, minimum), maximum)


def truncate_output(output: str, max_output_chars: int) -> tuple[str, int]:
    if len(output) <= max_output_chars:
        return output, 0
    half = max_output_chars // 2
    omitted = len(output) - max_output_chars
    return (
        output[:half]
        + f"\n\n... ({omitted:,} chars truncated) ...\n\n"
        + output[-half:],
        omitted,
    )


def format_session_poll(session_id: str, poll: SessionPoll) -> str:
    parts = [poll.output] if poll.output else []
    if poll.truncated_chars:
        parts.append(f"(output truncated by {poll.truncated_chars:,} chars)")
    if poll.timed_out:
        parts.append("Error: Command timed out; session was terminated.")
    if poll.terminated and not poll.timed_out:
        parts.append("Session terminated.")
    if poll.stdin_closed:
        parts.append("Stdin closed.")
    if poll.done:
        parts.append(f"Exit code: {poll.exit_code}")
    else:
        parts.append(f"Process running. session_id: {session_id}")
    parts.append(f"Elapsed: {poll.elapsed_s:.1f}s")
    return "\n".join(parts) if parts else "(no output yet)"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Session id returned by exec when yield_time_ms is used.",
                "minLength": 1,
            },
            "chars": {
                "type": "string",
                "description": "Text to write to stdin. Use an empty string to only poll output.",
            },
            "close_stdin": {
                "type": "boolean",
                "description": "Close stdin after writing chars.",
                "default": False,
            },
            "terminate": {
                "type": "boolean",
                "description": "Terminate the running exec session.",
                "default": False,
            },
            "yield_time_ms": {
                "type": "integer",
                "description": "Milliseconds to wait before returning recent output.",
                "minimum": 0,
                "maximum": MAX_YIELD_MS,
            },
            "max_output_chars": {
                "type": "integer",
                "description": "Maximum output characters to return from this poll.",
                "minimum": 1000,
                "maximum": MAX_OUTPUT_CHARS,
            },
            "max_output_tokens": {
                "type": "integer",
                "description": "Compatibility alias for max_output_chars.",
                "minimum": 1000,
                "maximum": MAX_OUTPUT_CHARS,
            },
        },
        "required": ["session_id"],
    },
)
class WriteStdinTool(Tool):
    """Write to or poll a running exec session."""

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
        owner_session_id: str | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER
        self._owner_session_id = owner_session_id

    @property
    def session_manager(self) -> ExecSessionManager:
        return self._manager

    @property
    def owner_session_id(self) -> str | None:
        return self._owner_session_id

    @property
    def name(self) -> str:
        return "write_stdin"

    @property
    def description(self) -> str:
        return (
            "Interact with a running exec session created by exec with yield_time_ms. "
            "Use chars='' to poll, chars to send stdin, close_stdin=true to send EOF, "
            "or terminate=true to stop the process."
        )

    async def execute(
        self,
        session_id: str,
        chars: str | None = None,
        close_stdin: bool = False,
        terminate: bool = False,
        yield_time_ms: int | None = None,
        max_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if max_output_chars is None:
                max_output_chars = max_output_tokens
            poll = await self._manager.write(
                session_id=session_id,
                chars=chars,
                close_stdin=close_stdin,
                terminate=terminate,
                owner_session_id=self._owner_session_id,
                yield_time_ms=clamp_session_int(yield_time_ms, DEFAULT_YIELD_MS, 0, MAX_YIELD_MS),
                max_output_chars=clamp_session_int(
                    max_output_chars,
                    DEFAULT_MAX_OUTPUT_CHARS,
                    1000,
                    MAX_OUTPUT_CHARS,
                ),
            )
            return format_session_poll(session_id, poll)
        except KeyError:
            return f"Error: exec session not found: {session_id}"
        except Exception as exc:
            return f"Error writing to exec session: {exc}"


@tool_parameters({"type": "object", "properties": {}})
class ListExecSessionsTool(Tool):
    """List active exec sessions."""

    read_only = True

    def __init__(
        self,
        *,
        manager: ExecSessionManager | None = None,
        owner_session_id: str | None = None,
    ) -> None:
        self._manager = manager or DEFAULT_EXEC_SESSION_MANAGER
        self._owner_session_id = owner_session_id

    @property
    def session_manager(self) -> ExecSessionManager:
        return self._manager

    @property
    def owner_session_id(self) -> str | None:
        return self._owner_session_id

    @property
    def name(self) -> str:
        return "list_exec_sessions"

    @property
    def description(self) -> str:
        return (
            "List active long-running exec sessions, including session_id, cwd, "
            "elapsed time, idle time, remaining timeout, and command preview."
        )

    async def execute(self, **kwargs: Any) -> str:
        try:
            sessions = await self._manager.list(owner_session_id=self._owner_session_id)
            if not sessions:
                return "No active exec sessions."
            lines = []
            for info in sessions:
                command = " ".join(info.command.split())
                if len(command) > 120:
                    command = command[:119] + "..."
                status = "exited" if info.returncode is not None else "running"
                lines.append(
                    f"{info.session_id} | {status} | elapsed={info.elapsed_s:.1f}s "
                    f"| idle={info.idle_s:.1f}s | remaining={info.remaining_s:.1f}s "
                    f"| cwd={info.cwd} | {command}"
                )
            return "\n".join(lines)
        except Exception as exc:
            return f"Error listing exec sessions: {exc}"
