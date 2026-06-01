"""Shell execution tool for simplified_chatbot."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.exec_session import (
    DEFAULT_EXEC_SESSION_MANAGER,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_YIELD_MS,
    MAX_OUTPUT_CHARS,
    MAX_YIELD_MS,
    clamp_session_int,
    format_session_poll,
)

_IS_WINDOWS = sys.platform == "win32"
_AGENT_BROWSER_TOKEN_PATTERN = re.compile(
    r"^(?P<exe>agent-browser(?:\.(?:cmd|bat|exe))?)(?=\s|$)",
    re.IGNORECASE,
)
_AGENT_BROWSER_EVAL_STDIN_PATTERN = re.compile(
    r"\bagent-browser\b.*\beval\b.*--stdin(?:\s|$)",
    re.IGNORECASE,
)
_EVAL_STDIN_HAS_INPUT_PATTERN = re.compile(
    r"(?:echo|cat|printf|<<<)\s.*\|\s*agent-browser\b"
    r"|<<['\"]?\w",
    re.IGNORECASE,
)
_WORKSPACE_BOUNDARY_NOTE = (
    "\n\nNote: this is a hard policy boundary, not a transient failure. "
    "Do not retry with shell tricks or alternative tools."
)


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
                "minLength": 1,
            },
            "working_dir": {
                "type": "string",
                "description": "Optional working directory for the command.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 60, max 600).",
                "minimum": 1,
                "maximum": 600,
            },
            "yield_time_ms": {
                "type": "integer",
                "description": (
                    "Optional milliseconds to wait before returning output. "
                    "When set, a still-running command returns a session_id. "
                    "Omit this field to keep one-shot exec behavior."
                ),
                "minimum": 0,
                "maximum": MAX_YIELD_MS,
            },
            "max_output_chars": {
                "type": "integer",
                "description": (
                    "Maximum output characters to return when yield_time_ms is used "
                    f"(default {DEFAULT_MAX_OUTPUT_CHARS}, max {MAX_OUTPUT_CHARS})."
                ),
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
        "required": ["command"],
    },
)
class ExecTool(Tool):
    """Execute a shell command within the configured workspace policy."""

    _MAX_TIMEOUT = 600
    _MAX_OUTPUT = 10_000
    _DENY_PATTERNS = (
        r"\brm\s+-[rf]{1,2}\b",
        r"\bdel\s+/[fq]\b",
        r"\brmdir\s+/s\b",
        r"(?:^|[;&|]\s*)format\b",
        r"\b(mkfs|diskpart)\b",
        r"\bdd\s+if=",
        r">\s*/dev/sd",
        r"\b(shutdown|reboot|poweroff)\b",
        r":\(\)\s*\{.*\};\s*:",
    )

    def __init__(
        self,
        *,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        timeout: int = 60,
        session_manager: Any | None = None,
        owner_session_id: str | None = None,
    ) -> None:
        self._workspace = workspace.resolve() if workspace is not None else Path.cwd().resolve()
        self._allowed_dir = allowed_dir.resolve() if allowed_dir is not None else None
        self._timeout = timeout
        self._chrome_port = None
        self._session_manager = session_manager or DEFAULT_EXEC_SESSION_MANAGER
        self._owner_session_id = owner_session_id

    def bind_chrome_debugging_port(self, port: int) -> None:
        self._chrome_port = port

    @property
    def session_manager(self) -> Any:
        return self._session_manager

    @property
    def owner_session_id(self) -> str | None:
        return self._owner_session_id
        
    @property
    def name(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return its output. "
            "Use this for tests, build, lint, or runtime verification. "
            "For long-running or interactive commands, pass yield_time_ms; "
            "if the command keeps running, exec returns a session_id. "
            "Output is truncated at 10,000 chars."
        )

    async def execute(
        self,
        command: str,
        working_dir: str | None = None,
        timeout: int | None = None,
        yield_time_ms: int | None = None,
        max_output_chars: int | None = None,
        max_output_tokens: int | None = None,
        **kwargs: Any,
    ) -> str:
        
        if _AGENT_BROWSER_EVAL_STDIN_PATTERN.search(command):
            if not _EVAL_STDIN_HAS_INPUT_PATTERN.search(command):
                return (
                    "Error: `agent-browser eval --stdin` must be used with piped input. "
                    "It is not interactive and will hang waiting for EOF.\n\n"
                    "Use one of these forms instead:\n"
                    '  echo "document.title" | agent-browser eval --stdin\n'
                    "  cat <<'EOF' | agent-browser eval --stdin\n"
                    "  document.querySelectorAll('a').length\n"
                    "  EOF\n"
                    "  agent-browser eval -b \"$(echo 'document.title' | base64)\""
                )

        try:
            command = self._maybe_inject_cdp_port(command)
        except ValueError as exc:
            return f"Error: {exc}"
        
        cwd = await self._resolve_working_dir(working_dir)
        if isinstance(cwd, str):
            return cwd

        guard_error = self._guard_command(command, cwd)
        if guard_error is not None:
            return guard_error

        effective_timeout = min(timeout or self._timeout, self._MAX_TIMEOUT)
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        if max_output_chars is None:
            max_output_chars = max_output_tokens

        if yield_time_ms is not None:
            try:
                session_id, poll = await self._session_manager.start(
                    command=command,
                    cwd=str(cwd),
                    env=env,
                    timeout=effective_timeout,
                    spawn=self._spawn_session,
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
            except Exception as exc:
                return f"Error executing command: {exc}"

        try:
            process = await self._spawn(command, cwd, env)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: Command timed out after {effective_timeout} seconds"

            parts: list[str] = []
            stdout_text = stdout.decode("utf-8", errors="replace")
            stderr_text = stderr.decode("utf-8", errors="replace")
            if stdout_text:
                parts.append(stdout_text)
            if stderr_text.strip():
                parts.append(f"STDERR:\n{stderr_text}")
            parts.append(f"\nExit code: {process.returncode}")
            result = "\n".join(parts) if parts else "(no output)"
            return self._truncate_output(result)
        except Exception as exc:
            return f"Error executing command: {exc}"

    async def _resolve_working_dir(self, working_dir: str | None) -> Path | str:
        if not working_dir:
            return self._workspace
        raw = Path(working_dir).expanduser()
        if not raw.is_absolute():
            raw = self._workspace / raw
        try:
            resolved = raw.resolve()
        except Exception:
            return "Error: working_dir could not be resolved" + _WORKSPACE_BOUNDARY_NOTE
        if not resolved.exists():
            return f"Error: working_dir not found: {working_dir}"
        if not resolved.is_dir():
            return f"Error: working_dir is not a directory: {working_dir}"
        if self._allowed_dir is not None and not _is_under(resolved, self._allowed_dir):
            return (
                "Error: working_dir is outside the configured workspace"
                + _WORKSPACE_BOUNDARY_NOTE
            )
        return resolved

    @staticmethod
    async def _spawn(
        command: str,
        cwd: Path,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        if _IS_WINDOWS:
            return await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash,
            "-l",
            "-c",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=env,
        )

    @staticmethod
    async def _spawn_session(
        command: str,
        cwd: str,
        env: dict[str, str],
    ) -> asyncio.subprocess.Process:
        if _IS_WINDOWS:
            return await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
        bash = shutil.which("bash") or "/bin/bash"
        return await asyncio.create_subprocess_exec(
            bash,
            "-l",
            "-c",
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    def _guard_command(self, command: str, cwd: Path) -> str | None:
        lowered = command.strip().lower()
        for pattern in self._DENY_PATTERNS:
            if re.search(pattern, lowered):
                return "Error: Command blocked by deny pattern filter"

        if self._allowed_dir is not None:
            if "..\\" in command or "../" in command:
                return (
                    "Error: Command blocked by safety guard (path traversal detected)"
                    + _WORKSPACE_BOUNDARY_NOTE
                )

            allowed = self._allowed_dir.resolve()
            executable_path = _extract_command_executable(command)
            for raw in _extract_absolute_paths(command):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    path = Path(expanded).expanduser().resolve()
                except Exception:
                    continue
                if executable_path is not None and path == executable_path:
                    continue
                if not _is_under(path, allowed):
                    return (
                        "Error: Command blocked by safety guard (path outside working dir)"
                        + _WORKSPACE_BOUNDARY_NOTE
                    )

            if not _is_under(cwd.resolve(), allowed) and cwd.resolve() != allowed:
                return (
                    "Error: working_dir is outside the configured workspace"
                    + _WORKSPACE_BOUNDARY_NOTE
                )
        return None

    def _truncate_output(self, result: str) -> str:
        if len(result) <= self._MAX_OUTPUT:
            return result
        half = self._MAX_OUTPUT // 2
        return (
            result[:half]
            + f"\n\n... ({len(result) - self._MAX_OUTPUT:,} chars truncated) ...\n\n"
            + result[-half:]
        )

    def _maybe_inject_cdp_port(self, command: str) -> str:
        """Rewrite `agent-browser ...` to `agent-browser --cdp <port> ...`."""
        if self._chrome_port is None:
            return command
        stripped = command.strip()
        match = _AGENT_BROWSER_TOKEN_PATTERN.match(stripped)
        if not match:
            return command
        if re.search(r"(?:^|\s)--cdp(?:\s|=)", command):
            return command
        
        # Insert "--cdp <port>" right after the agent-browser executable token.
        leading_ws_len = len(command) - len(stripped)
        leading_ws = command[:leading_ws_len]
        exe_token = match.group("exe")
        remainder = stripped[len(exe_token):]
        
        return f"{leading_ws}{exe_token} --cdp {self._chrome_port}{remainder}".rstrip()
        
def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _extract_absolute_paths(command: str) -> list[str]:
    win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]*", command)
    posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)
    # Filter out // (JS/C comments) and bare / or // with no real path component
    posix_paths = [p for p in posix_paths if re.search(r"/[A-Za-z0-9_.\-]", p)]
    home_paths = re.findall(r"(?:^|[\s>'\"])(~[^\s\"'>;|<]*)", command)
    return win_paths + posix_paths + home_paths


def _extract_command_executable(command: str) -> Path | None:
    stripped = command.strip()
    if not stripped:
        return None

    token = ""
    if stripped[0] in {'"', "'"}:
        quote = stripped[0]
        end = stripped.find(quote, 1)
        if end == -1:
            return None
        token = stripped[1:end]
    else:
        token = stripped.split(maxsplit=1)[0]

    try:
        candidate = Path(os.path.expandvars(token)).expanduser()
        if not candidate.is_absolute():
            return None
        return candidate.resolve()
    except Exception:
        return None
