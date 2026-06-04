"""MCP client integration for picobot tools."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import urllib.parse
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from simplified_chatbot.config.schema import MCPServerConfig
from simplified_chatbot.tools.base import Tool
from simplified_chatbot.tools.registry import ToolRegistry

_SANITIZE_RE = re.compile(r"_+")
_WINDOWS_SHELL_LAUNCHERS = frozenset(("npx", "npm", "pnpm", "yarn", "bunx"))

# How long to wait for a per-server lifecycle task to tear its transport down
# before we cancel and abandon it. A cleanly connected server closes well within
# this budget; the cap stops one stuck server from blocking shutdown/reload.
_SERVER_CLOSE_TIMEOUT = 10.0


def _sanitize_name(name: str) -> str:
    return _SANITIZE_RE.sub("_", re.sub(r"[^a-zA-Z0-9_-]", "_", name))


def _consume_background_task_result(task: asyncio.Task[Any]) -> None:
    with suppress(asyncio.CancelledError, Exception):
        task.result()


def _extract_nullable_branch(options: Any) -> tuple[dict[str, Any], bool] | None:
    if not isinstance(options, list):
        return None

    non_null: list[dict[str, Any]] = []
    saw_null = False
    for option in options:
        if not isinstance(option, dict):
            return None
        if option.get("type") == "null":
            saw_null = True
            continue
        non_null.append(option)

    if saw_null and len(non_null) == 1:
        return non_null[0], True
    return None


def _normalize_schema_for_openai(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    normalized = dict(schema)
    raw_type = normalized.get("type")
    if isinstance(raw_type, list):
        non_null = [item for item in raw_type if item != "null"]
        if "null" in raw_type and len(non_null) == 1:
            normalized["type"] = non_null[0]
            normalized["nullable"] = True

    for key in ("oneOf", "anyOf"):
        nullable_branch = _extract_nullable_branch(normalized.get(key))
        if nullable_branch is not None:
            branch, _ = nullable_branch
            merged = {k: v for k, v in normalized.items() if k != key}
            merged.update(branch)
            normalized = merged
            normalized["nullable"] = True
            break

    if "properties" in normalized and isinstance(normalized["properties"], dict):
        normalized["properties"] = {
            name: _normalize_schema_for_openai(prop) if isinstance(prop, dict) else prop
            for name, prop in normalized["properties"].items()
        }

    if "items" in normalized and isinstance(normalized["items"], dict):
        normalized["items"] = _normalize_schema_for_openai(normalized["items"])

    if normalized.get("type") != "object":
        return normalized

    normalized.setdefault("properties", {})
    normalized.setdefault("required", [])
    return normalized


async def _probe_http_url(url: str, timeout: float = 3.0) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if not port:
        port = 443 if parsed.scheme == "https" else 80
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def _windows_command_basename(command: str) -> str:
    return command.replace("\\", "/").rsplit("/", maxsplit=1)[-1].lower()


def _normalize_windows_stdio_command(
    command: str,
    args: list[str] | None,
    env: dict[str, str] | None,
) -> tuple[str, list[str], dict[str, str] | None]:
    normalized_args = list(args or [])
    if os.name != "nt":
        return command, normalized_args, env

    basename = _windows_command_basename(command)
    if basename in {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return command, normalized_args, env
    if basename.endswith((".exe", ".com")):
        return command, normalized_args, env

    resolved = shutil.which(command, path=(env or {}).get("PATH")) or command
    resolved_basename = _windows_command_basename(resolved)
    should_wrap = (
        basename in _WINDOWS_SHELL_LAUNCHERS
        or basename.endswith((".cmd", ".bat"))
        or resolved_basename.endswith((".cmd", ".bat"))
    )
    if not should_wrap:
        return command, normalized_args, env

    comspec = (env or {}).get("COMSPEC") or os.environ.get("COMSPEC") or "cmd.exe"
    return comspec, ["/d", "/c", command, *normalized_args], env


def _format_tool_result(result: Any) -> str:
    from mcp import types

    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        else:
            parts.append(str(block))
    return "\n".join(parts) or "(no output)"


def _format_resource_result(result: Any) -> str:
    from mcp import types

    parts: list[str] = []
    for block in getattr(result, "contents", []) or []:
        if isinstance(block, types.TextResourceContents):
            parts.append(block.text)
        elif isinstance(block, types.BlobResourceContents):
            parts.append(f"[Binary resource: {len(block.blob)} bytes]")
        else:
            parts.append(str(block))
    return "\n".join(parts) or "(no output)"


def _format_prompt_result(result: Any) -> str:
    from mcp import types

    parts: list[str] = []
    for message in getattr(result, "messages", []) or []:
        content = getattr(message, "content", None)
        if isinstance(content, types.TextContent):
            parts.append(content.text)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, types.TextContent):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
        elif content is not None:
            parts.append(str(content))
    return "\n".join(parts) or "(no output)"


@dataclass(slots=True)
class _WorkerCommand:
    op: str
    payload: Any
    future: asyncio.Future[Any]


class MCPToolWrapper(Tool):
    """Wrap one MCP tool as a picobot-native tool."""

    def __init__(
        self,
        manager: MCPConnectionManager,
        server_name: str,
        tool_def: Any,
        *,
        tool_timeout: int = 30,
    ) -> None:
        self._manager = manager
        self.server_name = server_name
        self.original_name = tool_def.name
        self.display_name = f"{server_name}::{tool_def.name}"
        self.description_zh = None
        self._name = _sanitize_name(f"mcp_{server_name}_{tool_def.name}")
        self._description = tool_def.description or tool_def.name
        raw_schema = getattr(tool_def, "inputSchema", None) or {
            "type": "object",
            "properties": {},
        }
        self._parameters = _normalize_schema_for_openai(raw_schema)
        self._tool_timeout = tool_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        return await self._manager.call_tool(
            self.server_name,
            self.original_name,
            kwargs,
            timeout=self._tool_timeout,
        )


class MCPResourceWrapper(Tool):
    """Wrap one MCP resource as a read-only picobot tool."""

    read_only = True

    def __init__(
        self,
        manager: MCPConnectionManager,
        server_name: str,
        resource_def: Any,
        *,
        resource_timeout: int = 30,
    ) -> None:
        self._manager = manager
        self.server_name = server_name
        self.original_name = resource_def.name
        self._uri = resource_def.uri
        self.display_name = f"{server_name}::resource::{resource_def.name}"
        self.description_zh = None
        self._name = _sanitize_name(f"mcp_{server_name}_resource_{resource_def.name}")
        description = resource_def.description or resource_def.name
        self._description = f"[MCP Resource] {description}\nURI: {self._uri}"
        self._parameters = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        self._resource_timeout = resource_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        del kwargs
        return await self._manager.read_resource(
            self.server_name,
            self._uri,
            timeout=self._resource_timeout,
        )


class MCPPromptWrapper(Tool):
    """Wrap one MCP prompt as a read-only picobot tool."""

    read_only = True

    def __init__(
        self,
        manager: MCPConnectionManager,
        server_name: str,
        prompt_def: Any,
        *,
        prompt_timeout: int = 30,
    ) -> None:
        self._manager = manager
        self.server_name = server_name
        self.original_name = prompt_def.name
        self.display_name = f"{server_name}::prompt::{prompt_def.name}"
        self.description_zh = None
        self._prompt_name = prompt_def.name
        self._name = _sanitize_name(f"mcp_{server_name}_prompt_{prompt_def.name}")
        description = prompt_def.description or prompt_def.name
        self._description = (
            f"[MCP Prompt] {description}\n"
            "Returns a filled prompt template that can be used as a workflow guide."
        )
        properties: dict[str, Any] = {}
        required: list[str] = []
        for arg in prompt_def.arguments or []:
            prop: dict[str, Any] = {"type": "string"}
            if getattr(arg, "description", None):
                prop["description"] = arg.description
            properties[arg.name] = prop
            if arg.required:
                required.append(arg.name)
        self._parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
        self._prompt_timeout = prompt_timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        prompt_args = {
            key: str(value)
            for key, value in kwargs.items()
            if value is not None
        }
        return await self._manager.get_prompt(
            self.server_name,
            self._prompt_name,
            prompt_args,
            timeout=self._prompt_timeout,
        )


class MCPConnectionManager:
    """Own live MCP connections and inject wrapped tools into registries."""

    def __init__(
        self,
        servers: Mapping[str, MCPServerConfig] | None = None,
    ) -> None:
        self._servers = dict(servers or {})
        self._server_sessions: dict[str, Any] = {}
        # In async_actor mode each connected server is owned by a long-lived
        # lifecycle task that both opens and later closes its AsyncExitStack, so
        # that anyio cancel scopes are always exited in the task that entered
        # them. sync_direct mode connects inline and tracks stacks separately.
        self._server_tasks: dict[str, asyncio.Task[None]] = {}
        self._server_close_events: dict[str, asyncio.Event] = {}
        self._sync_stacks: dict[str, AsyncExitStack] = {}
        self._server_wrappers: dict[str, list[Tool]] = {}
        self._tool_wrappers: dict[str, Tool] = {}
        # Every tool a connected server advertises (raw names), regardless of the
        # enabledTools filter, so the UI can offer per-tool toggles. Only known
        # while the server is connected; cleared when it disconnects.
        self._server_catalogs: dict[str, list[str]] = {}
        self._last_errors: dict[str, str] = {}
        self._pending_servers: set[str] = set()
        self._control_lock = asyncio.Lock()
        self._worker_queue: asyncio.Queue[_WorkerCommand] | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._mode: str | None = None

    @property
    def connected_server_names(self) -> set[str]:
        return set(self._server_sessions)

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tool_wrappers)

    @property
    def is_connected(self) -> bool:
        if not self._servers:
            return True
        return set(self._servers) <= set(self._server_sessions)

    def _has_live_task(self, server_name: str) -> bool:
        task = self._server_tasks.get(server_name)
        return task is not None and not task.done()

    def _set_server_session_and_wrappers(
        self,
        server_name: str,
        session: Any,
        wrappers: list[Tool],
        catalog: list[str],
    ) -> None:
        self._remove_server_state(server_name)
        self._server_sessions[server_name] = session
        self._server_catalogs[server_name] = list(catalog)
        self._server_wrappers[server_name] = list(wrappers)
        for wrapper in wrappers:
            self._tool_wrappers[wrapper.name] = wrapper

    def _remove_server_state(self, server_name: str) -> None:
        self._server_sessions.pop(server_name, None)
        self._server_catalogs.pop(server_name, None)
        self._pending_servers.discard(server_name)
        wrappers = self._server_wrappers.pop(server_name, [])
        for wrapper in wrappers:
            self._tool_wrappers.pop(wrapper.name, None)

    def _on_server_task_done(
        self,
        server_name: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._server_tasks.get(server_name) is task:
            self._server_tasks.pop(server_name, None)
            self._server_close_events.pop(server_name, None)
        _consume_background_task_result(task)

    def _abandon_server_task(self, server_name: str) -> None:
        """Stop tracking a server's lifecycle task without awaiting it.

        Used when a connection times out or fails: we signal/cancel the task so
        it tears itself down in its own task, but never block on a server that
        may be ignoring cancellation.
        """
        close_event = self._server_close_events.pop(server_name, None)
        if close_event is not None:
            close_event.set()
        task = self._server_tasks.pop(server_name, None)
        if task is not None and not task.done():
            task.cancel()

    async def _serve_single_server(
        self,
        server_name: str,
        cfg: MCPServerConfig,
        ready: asyncio.Future[bool],
        close_event: asyncio.Event,
    ) -> None:
        """Own one server's connection for its whole lifetime in a single task.

        The transport/session is opened here and, crucially, closed here too
        (on close_event or cancellation), so anyio cancel scopes are always
        exited in the same task that entered them.
        """
        stack: AsyncExitStack | None = None
        try:
            try:
                result = await _connect_single_server(self, server_name, cfg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_errors[server_name] = (
                    f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                )
                return
            if result is None:
                self._last_errors[server_name] = "Connection failed"
                return
            stack, session, wrappers, catalog = result
            self._set_server_session_and_wrappers(
                server_name, session, wrappers, catalog
            )
            self._last_errors.pop(server_name, None)
            if not ready.done():
                ready.set_result(True)
            await close_event.wait()
        finally:
            if not ready.done():
                ready.set_result(False)
            self._remove_server_state(server_name)
            if stack is not None:
                with suppress(Exception):
                    await stack.aclose()

    async def _connect_one_async(
        self,
        server_name: str,
        cfg: MCPServerConfig,
    ) -> None:
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[bool] = loop.create_future()
        close_event = asyncio.Event()
        task = asyncio.create_task(
            self._serve_single_server(server_name, cfg, ready, close_event),
        )
        task.add_done_callback(
            lambda finished, name=server_name: self._on_server_task_done(name, finished),
        )
        self._server_tasks[server_name] = task
        self._server_close_events[server_name] = close_event
        try:
            done, _ = await asyncio.wait({ready}, timeout=cfg.tool_timeout)
        except asyncio.CancelledError:
            self._abandon_server_task(server_name)
            raise
        finally:
            self._pending_servers.discard(server_name)
        if not done:
            self._last_errors[server_name] = (
                f"Connection timed out after {cfg.tool_timeout}s"
            )
            self._abandon_server_task(server_name)

    async def _connect_one_sync(
        self,
        server_name: str,
        cfg: MCPServerConfig,
    ) -> None:
        try:
            result = await asyncio.wait_for(
                _connect_single_server(self, server_name, cfg),
                timeout=cfg.tool_timeout,
            )
        except asyncio.TimeoutError:
            self._last_errors[server_name] = (
                f"Connection timed out after {cfg.tool_timeout}s"
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._last_errors[server_name] = (
                f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            )
            return
        finally:
            self._pending_servers.discard(server_name)
        if result is None:
            self._last_errors[server_name] = "Connection failed"
            return
        stack, session, wrappers, catalog = result
        self._sync_stacks[server_name] = stack
        self._set_server_session_and_wrappers(
            server_name, session, wrappers, catalog
        )
        self._last_errors.pop(server_name, None)

    async def _close_server(self, server_name: str) -> None:
        self._remove_server_state(server_name)
        sync_stack = self._sync_stacks.pop(server_name, None)
        if sync_stack is not None:
            with suppress(Exception):
                await sync_stack.aclose()
        close_event = self._server_close_events.pop(server_name, None)
        task = self._server_tasks.pop(server_name, None)
        if close_event is not None:
            close_event.set()
        if task is None or task.done():
            return
        try:
            done, _ = await asyncio.wait({task}, timeout=_SERVER_CLOSE_TIMEOUT)
        except asyncio.CancelledError:
            task.cancel()
            raise
        if not done:
            task.cancel()

    async def _close_all_servers(self) -> None:
        server_names = (
            set(self._server_tasks)
            | set(self._server_sessions)
            | set(self._sync_stacks)
        )
        for server_name in server_names:
            with suppress(Exception):
                await self._close_server(server_name)

    async def _connect_missing_servers(self) -> None:
        missing = {
            name: cfg
            for name, cfg in self._servers.items()
            if name not in self._server_sessions and not self._has_live_task(name)
        }
        self._pending_servers.update(missing)
        for server_name, server_cfg in missing.items():
            if self._mode == "sync_direct":
                await self._connect_one_sync(server_name, server_cfg)
            else:
                await self._connect_one_async(server_name, server_cfg)

    async def _connect_all_impl(self) -> None:
        await self._connect_missing_servers()

    async def _reload_servers_impl(
        self,
        servers: Mapping[str, MCPServerConfig],
    ) -> dict[str, Any]:
        next_servers = dict(servers)
        current_servers = dict(self._servers)
        current_names = set(current_servers)
        next_names = set(next_servers)

        removed = sorted(current_names - next_names)
        added = sorted(next_names - current_names)
        changed = sorted(
            name
            for name in current_names & next_names
            if _server_signature(current_servers[name]) != _server_signature(next_servers[name])
        )

        for name in [*removed, *changed]:
            await self._close_server(name)
            self._last_errors.pop(name, None)

        self._servers = next_servers
        await self._connect_missing_servers()

        failed = sorted(name for name in next_names if name not in self._server_sessions)
        unchanged = not removed and not added and not changed
        ok = not failed
        if failed:
            message = "MCP config reloaded, but some servers did not connect: " + ", ".join(failed)
        elif unchanged:
            message = "MCP config is already live."
        else:
            message = "MCP config reloaded successfully."
        return {
            "ok": ok,
            "message": message,
            "added": added,
            "changed": changed,
            "removed": removed,
            "connected": sorted(self._server_sessions),
            "failed": failed,
            "tool_count": len(self._tool_wrappers),
        }

    async def _call_tool_impl(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
    ) -> str:
        session = self._server_sessions.get(server_name)
        if session is None:
            return f"(MCP server '{server_name}' is not connected)"
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments=arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return f"(MCP tool call timed out after {timeout}s)"
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            return f"(MCP tool call failed: {type(exc).__name__})"
        return _format_tool_result(result)

    async def _read_resource_impl(
        self,
        server_name: str,
        uri: str,
        *,
        timeout: int,
    ) -> str:
        session = self._server_sessions.get(server_name)
        if session is None:
            return f"(MCP server '{server_name}' is not connected)"
        try:
            result = await asyncio.wait_for(session.read_resource(uri), timeout=timeout)
        except asyncio.TimeoutError:
            return f"(MCP resource read timed out after {timeout}s)"
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            return "(MCP resource read was cancelled)"
        except Exception as exc:
            return f"(MCP resource read failed: {type(exc).__name__})"
        return _format_resource_result(result)

    async def _get_prompt_impl(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str],
        *,
        timeout: int,
    ) -> str:
        session = self._server_sessions.get(server_name)
        if session is None:
            return f"(MCP server '{server_name}' is not connected)"
        try:
            result = await asyncio.wait_for(
                session.get_prompt(prompt_name, arguments=arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return f"(MCP prompt call timed out after {timeout}s)"
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            return "(MCP prompt call was cancelled)"
        except Exception as exc:
            return f"(MCP prompt call failed: {type(exc).__name__})"
        return _format_prompt_result(result)

    async def _worker_loop(self) -> None:
        queue = self._worker_queue
        if queue is None:
            return
        while True:
            command = await queue.get()
            if command.future.cancelled():
                continue
            try:
                if command.op == "connect_all":
                    result = await self._connect_all_impl()
                elif command.op == "reload_servers":
                    result = await self._reload_servers_impl(command.payload)
                elif command.op == "call_tool":
                    server_name, tool_name, arguments, timeout = command.payload
                    result = await self._call_tool_impl(
                        server_name,
                        tool_name,
                        arguments,
                        timeout=timeout,
                    )
                elif command.op == "read_resource":
                    server_name, uri, timeout = command.payload
                    result = await self._read_resource_impl(
                        server_name,
                        uri,
                        timeout=timeout,
                    )
                elif command.op == "get_prompt":
                    server_name, prompt_name, arguments, timeout = command.payload
                    result = await self._get_prompt_impl(
                        server_name,
                        prompt_name,
                        arguments,
                        timeout=timeout,
                    )
                elif command.op == "aclose_and_stop":
                    await self._close_all_servers()
                    if not command.future.cancelled():
                        command.future.set_result(None)
                    break
                else:
                    raise RuntimeError(f"Unknown MCP worker op: {command.op}")
            except Exception as exc:
                # The requester may have been cancelled (e.g. startup aborted),
                # which cancels its future. Setting a result/exception on an
                # already-cancelled future raises and would kill the worker,
                # stranding every later command (including aclose) forever.
                if not command.future.cancelled():
                    command.future.set_exception(exc)
            else:
                if not command.future.cancelled():
                    command.future.set_result(result)

    async def _ensure_worker(self) -> None:
        if self._mode == "sync_direct":
            raise RuntimeError(
                "This MCP manager is already running in sync mode; "
                "async hot reload is unavailable.",
            )
        if self._worker_task is not None and not self._worker_task.done():
            return
        async with self._control_lock:
            if self._worker_task is not None and not self._worker_task.done():
                return
            self._mode = "async_actor"
            self._worker_queue = asyncio.Queue()
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def _submit(self, op: str, payload: Any = None) -> Any:
        await self._ensure_worker()
        if self._worker_queue is None:
            raise RuntimeError("MCP worker queue is not available")
        future = asyncio.get_running_loop().create_future()
        await self._worker_queue.put(_WorkerCommand(op=op, payload=payload, future=future))
        return await future

    async def connect_all(self) -> None:
        await self._submit("connect_all")

    def connect_all_sync(self) -> None:
        if self._mode == "async_actor":
            raise RuntimeError(
                "connect_all_sync() cannot be used after async MCP startup. "
                "Use await connect_all() instead.",
            )
        self._mode = "sync_direct"
        asyncio.run(self._connect_all_impl())

    async def aclose(self) -> None:
        if self._mode == "sync_direct":
            self._mode = None
            await self._close_all_servers()
            self._pending_servers.clear()
            return
        task = self._worker_task
        if task is None or task.done():
            await self._close_all_servers()
            self._pending_servers.clear()
            self._mode = None
            return
        await self._submit("aclose_and_stop")
        await task
        self._worker_task = None
        self._worker_queue = None
        self._pending_servers.clear()
        self._mode = None

    async def reload_servers(
        self,
        servers: Mapping[str, MCPServerConfig],
    ) -> dict[str, Any]:
        return await self._submit("reload_servers", dict(servers))

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
    ) -> str:
        return await self._submit(
            "call_tool",
            (server_name, tool_name, arguments, timeout),
        )

    async def read_resource(
        self,
        server_name: str,
        uri: str,
        *,
        timeout: int,
    ) -> str:
        return await self._submit(
            "read_resource",
            (server_name, uri, timeout),
        )

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, str],
        *,
        timeout: int,
    ) -> str:
        return await self._submit(
            "get_prompt",
            (server_name, prompt_name, arguments, timeout),
        )

    def diagnostics(self) -> dict[str, Any]:
        servers: list[dict[str, Any]] = []
        for name in sorted(self._servers):
            config = self._servers[name]
            wrappers = self._server_wrappers.get(name, [])
            connecting = name in self._pending_servers and name not in self._server_sessions
            servers.append(
                {
                    "name": name,
                    "transport": _infer_transport(config),
                    "connected": name in self._server_sessions,
                    "connecting": connecting,
                    "tool_count": len(wrappers),
                    "tool_names": sorted(wrapper.name for wrapper in wrappers),
                    "available_tools": sorted(self._server_catalogs.get(name, [])),
                    "enabled_tools": list(config.enabled_tools),
                    "include_resources": config.include_resources,
                    "include_prompts": config.include_prompts,
                    "error": self._last_errors.get(name),
                }
            )
        return {
            "enabled": bool(self._servers),
            "configured_server_count": len(self._servers),
            "connected_server_count": len(self._server_sessions),
            "connecting_server_count": sum(
                1 for name in self._servers if name in self._pending_servers and name not in self._server_sessions
            ),
            "tool_count": len(self._tool_wrappers),
            "servers": servers,
        }

    def register_tools_into(
        self,
        registry: ToolRegistry,
        *,
        profile: str | None = None,
    ) -> None:
        del profile
        for tool_name in list(registry.tool_names):
            if tool_name.startswith("mcp_"):
                registry.unregister(tool_name)
        for wrapper in sorted(self._tool_wrappers.values(), key=lambda item: item.name):
            registry.register(wrapper)


async def _connect_single_server(
    manager: MCPConnectionManager,
    server_name: str,
    cfg: MCPServerConfig,
) -> tuple[AsyncExitStack, Any, list[Tool], list[str]] | None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    transport = cfg.type
    if transport is None:
        if cfg.command.strip():
            transport = "stdio"
        elif cfg.url.strip():
            transport = "sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp"
        else:
            return None

    stack = AsyncExitStack()
    await stack.__aenter__()
    try:
        transport_timeout = httpx.Timeout(
            connect=float(cfg.tool_timeout),
            read=float(cfg.tool_timeout),
            write=float(cfg.tool_timeout),
            pool=float(cfg.tool_timeout),
        )
        if transport == "stdio":
            command, args, env = _normalize_windows_stdio_command(
                cfg.command,
                cfg.args,
                cfg.env or None,
            )
            params = StdioServerParameters(
                command=command,
                args=args,
                env=env,
                cwd=cfg.cwd or None,
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        elif transport == "sse":
            if not await _probe_http_url(cfg.url):
                await stack.aclose()
                return None

            def httpx_client_factory(
                headers: dict[str, str] | None = None,
                timeout: httpx.Timeout | None = None,
                auth: httpx.Auth | None = None,
            ) -> httpx.AsyncClient:
                merged_headers = {
                    "Accept": "application/json, text/event-stream",
                    **(cfg.headers or {}),
                    **(headers or {}),
                }
                return httpx.AsyncClient(
                    headers=merged_headers or None,
                    follow_redirects=True,
                    timeout=timeout or transport_timeout,
                    auth=auth,
                )

            read, write = await stack.enter_async_context(
                sse_client(cfg.url, httpx_client_factory=httpx_client_factory),
            )
        elif transport == "streamableHttp":
            if not await _probe_http_url(cfg.url):
                await stack.aclose()
                return None
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers=cfg.headers or None,
                    follow_redirects=True,
                    timeout=transport_timeout,
                ),
            )
            read, write, _ = await stack.enter_async_context(
                streamable_http_client(cfg.url, http_client=http_client),
            )
        else:
            await stack.aclose()
            return None

        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        tools = await session.list_tools()
        # The full catalog (all advertised tools) before the enabledTools filter,
        # so the UI can show every tool with a per-tool enable toggle. Returned
        # to the caller and stored alongside the session, since the manager state
        # is reset when the new session is registered.
        catalog = [t.name for t in tools.tools]
        enabled_tools = set(cfg.enabled_tools)
        allow_all = "*" in enabled_tools
        wrappers: list[Tool] = []

        for tool_def in tools.tools:
            wrapped_name = _sanitize_name(f"mcp_{server_name}_{tool_def.name}")
            if (
                not allow_all
                and tool_def.name not in enabled_tools
                and wrapped_name not in enabled_tools
            ):
                continue
            wrappers.append(
                MCPToolWrapper(
                    manager,
                    server_name,
                    tool_def,
                    tool_timeout=cfg.tool_timeout,
                ),
            )
        if cfg.include_resources:
            try:
                resources = await session.list_resources()
                for resource_def in resources.resources:
                    wrappers.append(
                        MCPResourceWrapper(
                            manager,
                            server_name,
                            resource_def,
                            resource_timeout=cfg.tool_timeout,
                        ),
                    )
            except Exception:
                pass
        if cfg.include_prompts:
            try:
                prompts = await session.list_prompts()
                for prompt_def in prompts.prompts:
                    wrappers.append(
                        MCPPromptWrapper(
                            manager,
                            server_name,
                            prompt_def,
                            prompt_timeout=cfg.tool_timeout,
                        ),
                    )
            except Exception:
                pass
        return stack, session, wrappers, catalog
    except Exception:
        with suppress(Exception):
            await stack.aclose()
        raise


def _server_signature(cfg: MCPServerConfig) -> Any:
    return cfg.model_dump(mode="json")


def _infer_transport(cfg: MCPServerConfig) -> str:
    if cfg.type:
        return cfg.type
    if cfg.command.strip():
        return "stdio"
    if cfg.url.rstrip("/").endswith("/sse"):
        return "sse"
    if cfg.url.strip():
        return "streamableHttp"
    return "unknown"
