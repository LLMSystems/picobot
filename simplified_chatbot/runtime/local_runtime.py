"""Local multi-turn runtime built on top of SimplifiedChatbot."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.agent.types import Message, MessageContent, RunResult
from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.loader import load_config, resolve_config_path
from simplified_chatbot.config.schema import (
    MCPServerConfig,
    validate_mcp_server_config,
)
from simplified_chatbot.skills.loader import SkillsLoader
from simplified_chatbot.runtime.session_store import (
    AioSQLiteSessionMemoryStore,
    AioSQLiteSubagentStore,
    AioSQLiteSubagentEventStore,
    AioSQLiteSessionStore,
    AsyncSessionStore,
    InMemorySessionStore,
    JsonlSessionStore,
    SessionMemoryNoteRow,
    SessionMemoryRow,
    SessionStore,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager
from simplified_chatbot.tools.mcp import MCPConnectionManager
from simplified_chatbot.tools.shell import ExecTool


_MEMORY_TRIM_SAFETY_BUFFER_TOKENS = 1024
_MEMORY_SUMMARY_MAX_TOKENS = 1000
_SESSION_EVENT_SUBSCRIBER_QUEUE_MAX_SIZE = 128
_SESSION_EVENT_MERGEABLE_DELTA_EVENTS = {
    "assistant_delta",
    "assistant_reasoning_delta",
    "subagent_delta",
    "subagent_reasoning_delta",
}


@dataclass(slots=True)
class _PreparedMemoryContext:
    history: list[Message]
    system_prompt_override: str | None
    compacted_message_count: int
    runtime_notices: list[dict[str, str]]


class _SessionEventSubscriberQueue:
    """Bounded queue for live session SSE subscribers."""

    def __init__(self, *, max_size: int) -> None:
        self._items: list[dict[str, object]] = []
        self._has_items = asyncio.Event()
        self._max_size = max(1, max_size)
        self.dropped_events = 0

    async def get(self) -> dict[str, object]:
        while not self._items:
            self._has_items.clear()
            await self._has_items.wait()
        item = self._items.pop(0)
        if not self._items:
            self._has_items.clear()
        return item

    def empty(self) -> bool:
        return not self._items

    def put_nowait(self, item: dict[str, object]) -> None:
        event = item.get("event")
        if event == "__close__":
            self._make_room_for_critical()
            self._items.append(dict(item))
            self._has_items.set()
            return

        if len(self._items) >= self._max_size:
            if self._can_merge_delta(item) and self._merge_delta(item):
                self._has_items.set()
                return
            self._drop_or_merge_one()

        if len(self._items) >= self._max_size:
            self.dropped_events += 1
            return

        self._items.append(dict(item))
        self._has_items.set()

    def _can_merge_delta(self, item: dict[str, object]) -> bool:
        if item.get("event") not in _SESSION_EVENT_MERGEABLE_DELTA_EVENTS:
            return False
        data = item.get("data")
        return isinstance(data, dict) and isinstance(data.get("delta"), str)

    def _merge_delta(self, item: dict[str, object]) -> bool:
        if not self._items:
            return False
        incoming_data = item.get("data")
        if not isinstance(incoming_data, dict):
            return False
        incoming_delta = incoming_data.get("delta")
        if not isinstance(incoming_delta, str) or not incoming_delta:
            return False
        for existing in reversed(self._items):
            if not self._same_delta_stream(existing, item):
                continue
            existing_data = existing.get("data")
            if not isinstance(existing_data, dict):
                continue
            existing_data["delta"] = str(existing_data.get("delta") or "") + incoming_delta
            for key in ("seq", "created_at"):
                if key in item:
                    existing[key] = item[key]
            return True
        return False

    def _same_delta_stream(
        self,
        existing: dict[str, object],
        incoming: dict[str, object],
    ) -> bool:
        if existing.get("event") != incoming.get("event"):
            return False
        for key in ("session_id", "task_id", "run_id"):
            if existing.get(key) != incoming.get(key):
                return False
        return True

    def _drop_or_merge_one(self) -> None:
        for index, item in enumerate(list(self._items)):
            if item.get("event") not in _SESSION_EVENT_MERGEABLE_DELTA_EVENTS:
                del self._items[index]
                self.dropped_events += 1
                return
        for index, item in enumerate(list(self._items)):
            if self._can_merge_delta(item):
                del self._items[index]
                self.dropped_events += 1
                return
        if self._items:
            self._items.pop(0)
            self.dropped_events += 1

    def _make_room_for_critical(self) -> None:
        while len(self._items) >= self._max_size:
            self._drop_or_merge_one()


class LocalAgentRuntime:
    """Session-aware runtime that persists conversation history by session_id."""

    _DEFAULT_WORKSPACE_TREE_MAX = 200
    _DEFAULT_WORKSPACE_FILE_LIMIT = 2000
    _DEFAULT_MAX_UPLOAD_FILE_BYTES = 10 * 1024 * 1024
    _DEFAULT_MAX_UPLOAD_FILES_PER_REQUEST = 20

    def __init__(
        self,
        chatbot: SimplifiedChatbot,
        store: SessionStore | AsyncSessionStore | None = None,
        workspace_root_dir: str | Path | None = None,
        *,
        subagent_store: AioSQLiteSubagentStore | None = None,
        subagent_event_store: AioSQLiteSubagentEventStore | None = None,
        max_upload_file_bytes: int = _DEFAULT_MAX_UPLOAD_FILE_BYTES,
        max_upload_files_per_request: int = _DEFAULT_MAX_UPLOAD_FILES_PER_REQUEST,
        chrome_debugging_port: int | None = None,
        skills_loader: SkillsLoader | None = None,
        mcp_manager: MCPConnectionManager | None = None,
        config_path: str | Path | None = None,
        config_disabled_skills: set[str] | None = None,
    ) -> None:
        self.chatbot = chatbot
        self.store = store or InMemorySessionStore()
        self.memory_store = (
            AioSQLiteSessionMemoryStore(self.store.db_path)
            if self._memory_enabled and isinstance(self.store, AioSQLiteSessionStore)
            else None
        )
        self.skills_loader = skills_loader
        # Roots used to build per-user skill loaders. Custom skills live under
        # <skills_root>/users/<user_id>; the legacy global dir becomes a shared
        # read-only root. None when no skill library is configured.
        self._skills_root = getattr(skills_loader, "workspace_skills", None)
        self._builtin_skills_dir = getattr(skills_loader, "builtin_skills", None)
        # Config-level disables apply to every user's loader (e.g. hiding a
        # builtin globally); per-user enable/disable layers on top via state file.
        self._config_disabled_skills: set[str] = set(config_disabled_skills or set())
        self.subagent_store = subagent_store or _build_default_subagent_store(self.store)
        self.subagent_event_store = (
            subagent_event_store or _build_default_subagent_event_store(self.store)
        )
        self.workspace_manager = (
            SessionWorkspaceManager(workspace_root_dir, skills_loader=skills_loader)
            if workspace_root_dir is not None
            else None
        )
        self._session_chatbots: dict[str, Any] = {}
        self._session_agent_types: dict[str, str | None] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_event_subscribers: dict[str, list[_SessionEventSubscriberQueue]] = {}
        self._pending_internal_messages: dict[str, list[Message]] = {}
        self._subagent_event_seq: dict[str, int] = {}
        self._recent_subagent_events: dict[str, list[dict[str, object]]] = {}
        self._resume_requested: set[str] = set()
        self._background_tasks: dict[str, asyncio.Task[None]] = {}
        self.config_path = (
            Path(config_path).expanduser().resolve()
            if config_path is not None
            else None
        )
        self.mcp_manager = mcp_manager
        self.max_upload_file_bytes = max_upload_file_bytes
        self.max_upload_files_per_request = max_upload_files_per_request
        self.chrome_debugging_port = chrome_debugging_port
        self._bind_subagent_manager_callback()
        self._bind_subagent_tools(self.chatbot)
        self._refresh_mcp_tool_registries()
    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        store: SessionStore | AsyncSessionStore | None = None,
        store_dir: str | Path | None = None,
        workspace_root_dir: str | Path | None = None,
    ) -> "LocalAgentRuntime":
        config_file = Path(config_path).expanduser().resolve() if config_path is not None else None
        loaded_config = load_config(config_file) if config_file is not None else None
        mcp_manager: MCPConnectionManager | None = None
        if loaded_config is not None:
            mcp_manager = MCPConnectionManager(loaded_config.mcp_servers)
        bot = SimplifiedChatbot.from_config(config_file, mcp_manager=mcp_manager)
        if store is None:
            base_dir = (
                Path(store_dir).expanduser().resolve()
                if store_dir is not None
                else (config_file.parent / "sessions").resolve()
                if config_file is not None
                else (Path.cwd() / "sessions").resolve()
            )
            store = JsonlSessionStore(base_dir)
        resolved_workspace_root = _resolve_workspace_root_dir(
            config_file=config_file,
            configured_workspace_root=(
                loaded_config.workspace_root_dir
                if loaded_config is not None
                else None
            ),
            override_workspace_root=workspace_root_dir,
        )
        browser_config = getattr(loaded_config, "browser", None) if loaded_config is not None else None
        chrome_port = (
            browser_config.get("chromeDebuggingPort")
            if isinstance(browser_config, dict)
            else None
        )
        resolved_skills_dir = _resolve_skills_dir(loaded_config, config_file=config_file)
        if resolved_skills_dir is not None:
            resolved_skills_dir.mkdir(parents=True, exist_ok=True)
        skills_loader = SkillsLoader(
            skills_dir=resolved_skills_dir,
            disabled_skills=set(loaded_config.disabled_skills) if loaded_config is not None else set(),
        )
        return cls(
            chatbot=bot,
            store=store,
            subagent_store=_build_default_subagent_store(store),
            subagent_event_store=_build_default_subagent_event_store(store),
            workspace_root_dir=resolved_workspace_root,
            max_upload_file_bytes=(
                loaded_config.max_upload_file_bytes
                if loaded_config is not None
                else cls._DEFAULT_MAX_UPLOAD_FILE_BYTES
            ),
            max_upload_files_per_request=(
                loaded_config.max_upload_files_per_request
                if loaded_config is not None
                else cls._DEFAULT_MAX_UPLOAD_FILES_PER_REQUEST
            ),
            chrome_debugging_port=chrome_port,
            skills_loader=skills_loader,
            mcp_manager=mcp_manager,
            config_path=config_file,
            config_disabled_skills=(
                set(loaded_config.disabled_skills) if loaded_config is not None else set()
            ),
        )

    # ----- skill library management ----------------------------------------

    async def ensure_mcp_connected_async(self) -> None:
        """Connect configured MCP servers and refresh active tool registries."""
        if self.mcp_manager is None:
            return
        await self.mcp_manager.connect_all()
        self._refresh_mcp_tool_registries()

    def ensure_mcp_connected(self) -> None:
        """Sync wrapper for connecting configured MCP servers."""
        if self.mcp_manager is None:
            return
        self.mcp_manager.connect_all_sync()
        self._refresh_mcp_tool_registries()

    async def close_mcp_async(self) -> None:
        """Close live MCP connections."""
        if self.mcp_manager is None:
            return
        await self.mcp_manager.aclose()
        self._refresh_mcp_tool_registries()

    def get_mcp_status(self) -> dict[str, object]:
        """Return MCP connection diagnostics for API consumers."""
        manager = self.mcp_manager
        if manager is None:
            return {
                "supported": False,
                "reload_supported": False,
                "enabled": False,
                "configured_server_count": 0,
                "connected_server_count": 0,
                "connecting_server_count": 0,
                "tool_count": 0,
                "servers": [],
            }
        return {
            "supported": True,
            "reload_supported": self.config_path is not None,
            **manager.diagnostics(),
        }

    async def reload_mcp_async(self) -> dict[str, object]:
        """Reload MCP config from disk and reconcile live connections."""
        if self.config_path is None:
            raise RuntimeError("MCP reload is unavailable without a config file path")
        if self.mcp_manager is None:
            raise RuntimeError("MCP runtime is not initialized")

        loaded_config = load_config(self.config_path)
        summary = await self.mcp_manager.reload_servers(loaded_config.mcp_servers)
        self._refresh_mcp_tool_registries()
        chatbot_config = getattr(self.chatbot, "config", None)
        if chatbot_config is not None and hasattr(chatbot_config, "mcp_servers"):
            chatbot_config.mcp_servers = loaded_config.mcp_servers
        return {
            **summary,
            **self.get_mcp_status(),
        }

    def _read_raw_mcp_config(self) -> tuple[Path, dict[str, Any], str]:
        """Read config.json as raw JSON, without resolving ${ENV} placeholders.

        Editing MCP servers must round-trip the raw document so we never write
        resolved secrets (e.g. an expanded ``${GITHUB_PAT}``) back to disk.
        Returns the path, the parsed document, and the key under which servers
        live (``mcpServers`` or ``mcp_servers``).
        """
        if self.config_path is None:
            raise RuntimeError("MCP editing is unavailable without a config file path")
        path = resolve_config_path(self.config_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("Config file root must be a JSON object")
        key = "mcp_servers" if "mcp_servers" in data else "mcpServers"
        return path, data, key

    def get_mcp_raw_servers(self) -> dict[str, Any]:
        """Return on-disk MCP server configs with ${ENV} placeholders intact."""
        _path, data, key = self._read_raw_mcp_config()
        servers = data.get(key) or {}
        if not isinstance(servers, dict):
            raise RuntimeError(f"Config '{key}' must be a JSON object")
        return servers

    async def upsert_mcp_server_async(
        self,
        name: str,
        raw_server: dict[str, Any],
    ) -> dict[str, object]:
        """Validate and persist one MCP server to config.json, then reconcile."""
        if self.mcp_manager is None:
            raise RuntimeError("MCP runtime is not initialized")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Server name must not be empty")
        # Validate field shape + transport rules on the raw input, so we never
        # trigger ${ENV} resolution while checking a config that is being edited.
        server = MCPServerConfig.model_validate(raw_server)
        validate_mcp_server_config(clean_name, server)
        path, data, key = self._read_raw_mcp_config()
        servers = data.get(key)
        if not isinstance(servers, dict):
            servers = {}
        servers[clean_name] = server.model_dump(
            mode="json",
            by_alias=True,
            exclude_defaults=True,
        )
        data[key] = servers
        self._write_raw_mcp_config(path, data)
        return await self.reload_mcp_async()

    async def remove_mcp_server_async(self, name: str) -> dict[str, object]:
        """Remove one MCP server from config.json, then reconcile connections."""
        if self.mcp_manager is None:
            raise RuntimeError("MCP runtime is not initialized")
        path, data, key = self._read_raw_mcp_config()
        servers = data.get(key)
        if not isinstance(servers, dict) or name not in servers:
            raise KeyError(name)
        del servers[name]
        data[key] = servers
        self._write_raw_mcp_config(path, data)
        return await self.reload_mcp_async()

    @staticmethod
    def _write_raw_mcp_config(path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _require_skills_loader(self) -> SkillsLoader:
        if self.skills_loader is None:
            raise RuntimeError("Skill library is not available in this runtime")
        return self.skills_loader

    def _skills_loader_for_user(self, user_id: int | None) -> SkillsLoader:
        """Return the skill loader scoped to one user.

        Writable custom skills live under ``<skills_root>/users/<user_id>``;
        the legacy global dir is exposed as a shared read-only root and builtin
        skills stay shared. ``user_id is None`` (non-auth / library-less local
        runtime) falls back to the legacy global loader so existing callers and
        tests keep working unchanged.
        """
        if self.skills_loader is None:
            raise RuntimeError("Skill library is not available in this runtime")
        if user_id is None or self._skills_root is None:
            return self.skills_loader
        user_dir = self._skills_root / "users" / str(user_id)
        return SkillsLoader(
            skills_dir=user_dir,
            shared_skills_dir=self._skills_root,
            builtin_skills_dir=self._builtin_skills_dir,
            disabled_skills=set(self._config_disabled_skills),
        )

    def list_skills(self, user_id: int | None = None) -> list[dict[str, object]]:
        """List every skill (builtin + shared + this user's custom) with flags."""
        return self._skills_loader_for_user(user_id).list_all_skills()

    def create_skill(
        self,
        name: str,
        content: str,
        files: dict[str, bytes] | None = None,
        *,
        user_id: int | None = None,
    ) -> None:
        """Create or overwrite a custom skill in the user's own library."""
        self._skills_loader_for_user(user_id).create_skill(name, content, files=files)

    def delete_skill(self, name: str, *, user_id: int | None = None) -> None:
        """Delete a custom skill from the user's own library."""
        self._skills_loader_for_user(user_id).delete_skill(name)

    def set_skill_disabled(
        self,
        name: str,
        disabled: bool,
        *,
        user_id: int | None = None,
    ) -> None:
        """Enable or disable a skill for the user's newly created sessions."""
        self._skills_loader_for_user(user_id).set_skill_disabled(name, disabled)

    def handle_message(
        self,
        session_id: str,
        message: str,
        *,
        model_override: str | None = None,
    ) -> RunResult:
        return self.handle_input_with_events(
            session_id,
            message,
            model_override=model_override,
            on_event=None,
        )

    def handle_input(
        self,
        session_id: str,
        content: MessageContent,
        *,
        model_override: str | None = None,
    ) -> RunResult:
        return self.handle_input_with_events(
            session_id,
            content,
            model_override=model_override,
            on_event=None,
        )

    def handle_message_with_events(
        self,
        session_id: str,
        message: str,
        *,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        return self.handle_input_with_events(
            session_id,
            message,
            model_override=model_override,
            on_event=on_event,
        )

    def handle_input_with_events(
        self,
        session_id: str,
        content: MessageContent,
        *,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_input_async(...) or handle_message_async(...) instead of "
                "handle_input(...)/handle_message(...).",
            )
        self.ensure_mcp_connected()
        run_id = _generate_run_id()
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            _build_run_started_payload(session_id, content),
        )
        resolved_model = self._resolve_model_override(model_override)
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = _invoke_chatbot_method(
            chatbot.run,
            content,
            history=history,
            model_override=resolved_model,
            on_event=event_callback,
        )
        self.store.save_history(
            session_id,
            _prepare_history_for_persistence(
                _stamp_run_id(result.messages, len(history), run_id),
            ),
        )
        return result

    def handle_message_stream(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        return self.handle_input_stream(
            session_id,
            message,
            on_delta=on_delta,
            model_override=model_override,
            on_event=on_event,
        )

    def handle_input_stream(
        self,
        session_id: str,
        content: MessageContent,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_input_stream_async(...) or handle_message_stream_async(...) "
                "instead of handle_input_stream(...)/handle_message_stream(...).",
            )
        self.ensure_mcp_connected()
        run_id = _generate_run_id()
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            _build_run_started_payload(session_id, content),
        )
        resolved_model = self._resolve_model_override(model_override)
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = _invoke_chatbot_method(
            chatbot.run_stream,
            content,
            history=history,
            on_delta=on_delta,
            model_override=resolved_model,
            on_event=event_callback,
        )
        self.store.save_history(
            session_id,
            _prepare_history_for_persistence(
                _stamp_run_id(result.messages, len(history), run_id),
            ),
        )
        return result

    async def handle_message_async(
        self,
        session_id: str,
        message: str,
        *,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        return await self.handle_input_async(
            session_id,
            message,
            model_override=model_override,
            on_event=on_event,
        )

    async def handle_input_async(
        self,
        session_id: str,
        content: MessageContent,
        *,
        model_override: str | None = None,
        subagent_model_override: str | None = None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        async def runner() -> RunResult:
            await self.ensure_mcp_connected_async()
            run_id = _generate_run_id()
            event_callback = _build_runtime_event_callback(session_id, on_event)
            _emit_runtime_event(
                event_callback,
                "run_started",
                _build_run_started_payload(session_id, content),
            )
            resolved_model = self._resolve_model_override(model_override)
            resolved_subagent_model = self._resolve_model_override(subagent_model_override)
            history = await self._load_history_async(session_id)
            injected = self._pop_pending_internal_messages(session_id)
            try:
                prepared = await self._prepare_memory_context_async(
                    session_id,
                    content,
                    history=history,
                    injected=injected,
                    model_override=resolved_model,
                    system_prompt_override=system_prompt_override,
                    max_tokens_override=max_tokens_override,
                    on_event=event_callback,
                )
                with self._apply_subagent_model_override(session_id, resolved_subagent_model):
                    result = await self._run_chat_async(
                        session_id,
                        content,
                        history=prepared.history,
                        model_override=resolved_model,
                        temperature_override=temperature_override,
                        max_tokens_override=max_tokens_override,
                        max_iterations_override=max_iterations_override,
                        system_prompt_override=prepared.system_prompt_override,
                        disabled_tools=disabled_tools,
                        on_event=event_callback,
                    )
            except Exception:
                self._restore_pending_internal_messages(session_id, injected)
                raise
            persisted_messages = self._attach_runtime_notices(
                _stamp_run_id(result.messages, len(prepared.history), run_id),
                prepared.runtime_notices,
            )
            await self._save_history_async(
                session_id,
                self._restore_full_history_after_memory(
                    history,
                    persisted_messages,
                    prepared.compacted_message_count,
                ),
            )
            return result

        return await self._run_with_session_lock(session_id, runner)

    async def handle_message_stream_async(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        return await self.handle_input_stream_async(
            session_id,
            message,
            on_delta=on_delta,
            model_override=model_override,
            on_event=on_event,
        )

    async def handle_input_stream_async(
        self,
        session_id: str,
        content: MessageContent,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        subagent_model_override: str | None = None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        async def runner() -> RunResult:
            await self.ensure_mcp_connected_async()
            run_id = _generate_run_id()
            event_callback = _build_runtime_event_callback(session_id, on_event)
            _emit_runtime_event(
                event_callback,
                "run_started",
                _build_run_started_payload(session_id, content),
            )
            resolved_model = self._resolve_model_override(model_override)
            resolved_subagent_model = self._resolve_model_override(subagent_model_override)
            history = await self._load_history_async(session_id)
            injected = self._pop_pending_internal_messages(session_id)
            try:
                prepared = await self._prepare_memory_context_async(
                    session_id,
                    content,
                    history=history,
                    injected=injected,
                    model_override=resolved_model,
                    system_prompt_override=system_prompt_override,
                    max_tokens_override=max_tokens_override,
                    on_event=event_callback,
                )
                with self._apply_subagent_model_override(session_id, resolved_subagent_model):
                    result = await self._run_chat_stream_async(
                        session_id,
                        content,
                        history=prepared.history,
                        on_delta=on_delta,
                        model_override=resolved_model,
                        temperature_override=temperature_override,
                        max_tokens_override=max_tokens_override,
                        max_iterations_override=max_iterations_override,
                        system_prompt_override=prepared.system_prompt_override,
                        disabled_tools=disabled_tools,
                        on_event=event_callback,
                    )
            except Exception:
                self._restore_pending_internal_messages(session_id, injected)
                raise
            persisted_messages = self._attach_runtime_notices(
                _stamp_run_id(result.messages, len(prepared.history), run_id),
                prepared.runtime_notices,
            )
            await self._save_history_async(
                session_id,
                self._restore_full_history_after_memory(
                    history,
                    persisted_messages,
                    prepared.compacted_message_count,
                ),
            )
            return result

        return await self._run_with_session_lock(session_id, runner)

    def reset_session(self, session_id: str) -> None:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use reset_session_async(...) instead of reset_session(...).",
            )
        self._terminate_exec_sessions_for_session(session_id)
        self.store.delete_session(session_id)
        self._session_chatbots.pop(session_id, None)
        self._session_agent_types.pop(session_id, None)
        self._session_locks.pop(session_id, None)
        self._session_event_subscribers.pop(session_id, None)
        self._pending_internal_messages.pop(session_id, None)
        self._resume_requested.discard(session_id)
        self._background_tasks.pop(session_id, None)

    def list_sessions(self) -> list[str]:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use list_sessions_async(...) instead of list_sessions(...).",
            )
        return self.store.list_sessions()

    def list_session_summaries(self) -> list[dict[str, object]]:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use list_session_summaries_async(...) instead of list_session_summaries(...).",
            )
        return [
            self._build_session_summary(
                session_id,
                self.store.load_history(session_id),
                self.store.get_session_metadata(session_id),
            )
            for session_id in self.store.list_sessions()
        ]

    def create_session(
        self,
        *,
        title: str | None = None,
        session_id: str | None = None,
        agent_type: str | None = None,
    ) -> dict[str, object]:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use create_session_async(...) instead of create_session(...).",
            )
        resolved_session_id = session_id or _generate_session_id()
        resolved_agent_type = _normalize_agent_type(agent_type)
        metadata = self.store.create_session(
            resolved_session_id,
            {"title": _normalize_session_title(title), "agent_type": resolved_agent_type},
        )
        self._session_agent_types[resolved_session_id] = resolved_agent_type
        if self.workspace_manager is not None:
            self.workspace_manager.ensure_workspace(resolved_session_id)
        return self._build_session_summary(resolved_session_id, [], metadata)

    def rename_session(self, session_id: str, title: str) -> dict[str, object]:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use rename_session_async(...) instead of rename_session(...).",
            )
        metadata = self.store.update_session_metadata(
            session_id,
            {"title": _normalize_session_title(title)},
        )
        if metadata is None:
            raise KeyError(session_id)
        return self._build_session_summary(
            session_id,
            self.store.load_history(session_id),
            metadata,
        )

    async def reset_session_async(self, session_id: str) -> None:
        background_task = self._background_tasks.pop(session_id, None)
        if background_task is not None and not background_task.done():
            background_task.cancel()
            try:
                await background_task
            except asyncio.CancelledError:
                pass
        await self._terminate_exec_sessions_for_session_async(session_id)
        if isinstance(self.store, AsyncSessionStore):
            await self.store.delete_session(session_id)
        else:
            await asyncio.to_thread(self.store.delete_session, session_id)
        if self.memory_store is not None:
            await self.memory_store.delete_session_data(session_id)
        self._session_chatbots.pop(session_id, None)
        self._session_agent_types.pop(session_id, None)
        self._session_locks.pop(session_id, None)
        self._session_event_subscribers.pop(session_id, None)
        self._pending_internal_messages.pop(session_id, None)
        self._resume_requested.discard(session_id)

    async def list_sessions_async(self, user_id: int | None = None) -> list[str]:
        if isinstance(self.store, AsyncSessionStore):
            # Only the AioSQLite store supports the user_id filter; call the
            # plain signature when not filtering so other async stores still work.
            if user_id is None:
                return await self.store.list_sessions()
            return await self.store.list_sessions(user_id=user_id)
        # Sync stores (InMemory/Jsonl/SQLite) are deprecated and have no user
        # column, so they cannot filter — return everything as before.
        return await asyncio.to_thread(self.store.list_sessions)

    async def list_session_summaries_async(
        self,
        user_id: int | None = None,
    ) -> list[dict[str, object]]:
        session_ids = await self.list_sessions_async(user_id=user_id)
        summaries: list[dict[str, object]] = []
        for session_id in session_ids:
            history = await self._load_history_async(session_id)
            metadata = await self._load_session_metadata_async(session_id)
            summaries.append(self._build_session_summary(session_id, history, metadata))
        return summaries

    async def get_session_summary_async(self, session_id: str) -> dict[str, object] | None:
        history = await self._load_history_async(session_id)
        metadata = await self._load_session_metadata_async(session_id)
        if not history and metadata is None:
            return None
        return self._build_session_summary(session_id, history, metadata)

    async def list_subagent_runs_async(
        self,
        session_id: str,
        *,
        phase: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        if self.subagent_store is None:
            return []
        return await self.subagent_store.list_runs(
            parent_session_id=session_id,
            phase=phase,
            limit=limit,
        )

    async def get_subagent_run_async(
        self,
        session_id: str,
        task_id: str,
    ) -> dict[str, object] | None:
        if self.subagent_store is None:
            return None
        payload = await self.subagent_store.get_run(task_id)
        if payload is None:
            return None
        return payload if payload.get("parent_session_id") == session_id else None

    async def list_subagent_events_async(
        self,
        session_id: str,
        task_id: str,
        *,
        after_seq: int | None = None,
        limit: int = 500,
    ) -> list[dict[str, object]]:
        if self.subagent_event_store is None:
            return []
        return await self.subagent_event_store.list_events(
            task_id,
            parent_session_id=session_id,
            after_seq=after_seq,
            limit=limit,
        )

    async def get_workspace_root_async(self, session_id: str) -> Path:
        """Return the resolved workspace root for one existing session."""
        if self.workspace_manager is None:
            raise RuntimeError("Workspace API is not available because session workspaces are disabled")
        summary = await self.get_session_summary_async(session_id)
        if summary is None:
            raise KeyError(session_id)
        return self.workspace_manager.ensure_workspace(session_id)

    async def list_workspace_tree_async(
        self,
        session_id: str,
        *,
        path: str = ".",
        recursive: bool = False,
        max_entries: int | None = None,
    ) -> dict[str, object]:
        """List one directory inside the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_dir():
            raise NotADirectoryError(path)

        limit = max_entries or self._DEFAULT_WORKSPACE_TREE_MAX
        entries: list[dict[str, object]] = []
        total = 0
        iterable = target.rglob("*") if recursive else target.iterdir()
        for item in sorted(iterable, key=lambda candidate: _relative_posix(candidate, workspace)):
            total += 1
            if len(entries) >= limit:
                continue
            item_path = _relative_posix(item, workspace)
            entries.append(
                {
                    "path": item_path,
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "updated_at": _mtime_to_utc(item),
                },
            )

        return {
            "session_id": session_id,
            "path": relative_path,
            "entries": entries,
            "truncated": total > limit,
        }

    async def read_workspace_file_async(
        self,
        session_id: str,
        *,
        path: str,
        offset: int = 1,
        limit: int | None = None,
    ) -> dict[str, object]:
        """Read one UTF-8 text file from the session workspace."""
        if offset < 1:
            raise ValueError("offset must be >= 1")
        effective_limit = limit or self._DEFAULT_WORKSPACE_FILE_LIMIT
        if effective_limit < 1:
            raise ValueError("limit must be >= 1")

        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_file():
            raise IsADirectoryError(path)

        raw = await asyncio.to_thread(target.read_bytes)
        text = raw.decode("utf-8")
        normalized = text.replace("\r\n", "\n")
        lines = normalized.splitlines(keepends=True)
        line_count = len(lines)

        if line_count == 0:
            content = ""
            truncated = False
        else:
            if offset > line_count:
                raise ValueError(f"offset {offset} is beyond end of file ({line_count} lines)")
            start = offset - 1
            end = min(start + effective_limit, line_count)
            content = "".join(lines[start:end])
            truncated = end < line_count

        return {
            "session_id": session_id,
            "path": relative_path,
            "content": content,
            "encoding": "utf-8",
            "truncated": truncated,
            "line_count": line_count,
        }

    async def resolve_workspace_file_async(
        self,
        session_id: str,
        *,
        path: str,
    ) -> tuple[str, Path]:
        """Resolve a workspace path to an absolute file path, validating it is a regular file."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_file():
            raise IsADirectoryError(path)
        return relative_path, target

    async def upload_workspace_files_async(
        self,
        session_id: str,
        *,
        path: str = ".",
        files: list["UploadFileInput"],
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Upload one or more files into the session workspace."""
        if not files:
            raise WorkspaceUploadNoFilesError("no files were provided")
        if len(files) > self.max_upload_files_per_request:
            raise WorkspaceUploadTooManyFilesError(
                f"too many files: {len(files)} > {self.max_upload_files_per_request}",
            )

        workspace = await self.get_workspace_root_async(session_id)
        relative_dir, target_dir = _resolve_workspace_relative_path(workspace, path)
        if not target_dir.exists():
            raise FileNotFoundError(path)
        if not target_dir.is_dir():
            raise NotADirectoryError(path)

        uploaded: list[dict[str, object]] = []
        skipped: list[dict[str, object]] = []
        for item in files:
            if len(item.content) > self.max_upload_file_bytes:
                raise WorkspaceUploadFileTooLargeError(
                    f"file '{item.name}' exceeds max size {self.max_upload_file_bytes} bytes",
                )

            if item.relative_path:
                # Folder upload: validate each path component and resolve target
                rel = item.relative_path.replace("\\", "/").strip("/")
                parts = rel.split("/")
                for part in parts:
                    _validate_upload_filename(part)
                target = target_dir.joinpath(*parts)
                display_name = parts[-1]
            else:
                _validate_upload_filename(item.name)
                target = target_dir / item.name
                display_name = item.name

            relative_path = _relative_posix(target, workspace)
            already_exists = target.exists()
            if already_exists and target.is_dir():
                raise WorkspaceFilenameInvalidError(
                    f"target path '{relative_path}' is an existing directory",
                )
            if already_exists and not overwrite:
                skipped.append(
                    {
                        "name": display_name,
                        "reason": "already_exists",
                    },
                )
                continue

            await asyncio.to_thread(_atomic_write_bytes, target, item.content)
            uploaded.append(
                {
                    "path": relative_path,
                    "name": display_name,
                    "size": len(item.content),
                    "content_type": item.content_type,
                    "overwritten": already_exists,
                },
            )

        return {
            "session_id": session_id,
            "path": relative_dir,
            "uploaded": uploaded,
            "skipped": skipped,
        }

    async def delete_workspace_file_async(
        self,
        session_id: str,
        *,
        path: str,
    ) -> dict[str, object]:
        """Delete one file from the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_file():
            raise IsADirectoryError(path)

        await asyncio.to_thread(target.unlink)
        return {
            "session_id": session_id,
            "path": relative_path,
            "deleted": True,
        }

    async def save_workspace_file_async(
        self,
        session_id: str,
        *,
        path: str,
        content: str,
    ) -> dict[str, object]:
        """Overwrite a text file in the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if relative_path == ".":
            raise ValueError("path must not be the workspace root")
        if target.exists() and target.is_dir():
            raise IsADirectoryError(path)
        if not target.parent.exists():
            raise FileNotFoundError(str(target.parent))
        encoded = content.encode("utf-8")
        await asyncio.to_thread(_atomic_write_bytes, target, encoded)
        stat = target.stat()
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        return {
            "session_id": session_id,
            "path": relative_path,
            "saved": True,
            "size": stat.st_size,
            "updated_at": updated_at,
        }

    async def download_workspace_zip_async(
        self,
        session_id: str,
        *,
        path: str = ".",
    ) -> tuple[str, object]:
        """Return (filename, zip_bytes_io) for the given workspace path."""
        import io
        import zipfile as _zipfile

        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_dir():
            raise NotADirectoryError(path)

        zip_name = "workspace.zip" if relative_path == "." else f"{target.name}.zip"

        def _build_zip() -> io.BytesIO:
            buf = io.BytesIO()
            with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(target.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(target))
            buf.seek(0)
            return buf

        buf = await asyncio.to_thread(_build_zip)
        return zip_name, buf

    async def create_workspace_file_async(
        self,
        session_id: str,
        *,
        path: str,
        content: str = "",
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Create a new text file in the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if relative_path == ".":
            raise ValueError("path must not be the workspace root")
        if target.exists():
            if target.is_dir():
                raise IsADirectoryError(path)
            if not overwrite:
                raise WorkspaceFileAlreadyExistsError(path)
        if not target.parent.exists():
            raise FileNotFoundError(str(target.parent))
        encoded = content.encode("utf-8")
        await asyncio.to_thread(_atomic_write_bytes, target, encoded)
        return {
            "session_id": session_id,
            "path": relative_path,
            "created": True,
        }

    async def delete_workspace_directory_async(
        self,
        session_id: str,
        *,
        path: str,
        recursive: bool = False,
    ) -> dict[str, object]:
        """Delete a directory from the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if relative_path == ".":
            raise WorkspaceDeleteRootForbiddenError("cannot delete workspace root")
        if not target.exists():
            raise FileNotFoundError(path)
        if not target.is_dir():
            raise NotADirectoryError(path)
        if not recursive and any(target.iterdir()):
            raise WorkspaceDirectoryNotEmptyError(path)
        await asyncio.to_thread(shutil.rmtree, target)
        return {
            "session_id": session_id,
            "path": relative_path,
            "deleted": True,
        }

    async def create_workspace_directory_async(
        self,
        session_id: str,
        *,
        path: str,
    ) -> dict[str, object]:
        """Create one directory inside the session workspace."""
        workspace = await self.get_workspace_root_async(session_id)
        relative_path, target = _resolve_workspace_relative_path(workspace, path)
        if target.exists():
            if not target.is_dir():
                raise NotADirectoryError(path)
            return {
                "session_id": session_id,
                "path": relative_path,
                "created": False,
            }

        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
        return {
            "session_id": session_id,
            "path": relative_path,
            "created": True,
        }

    async def move_workspace_entry_async(
        self,
        session_id: str,
        *,
        src: str,
        dst: str,
        overwrite: bool = False,
    ) -> dict[str, object]:
        """Move or rename one workspace file or directory."""
        workspace = await self.get_workspace_root_async(session_id)
        src_relative, src_target = _resolve_workspace_relative_path(workspace, src)
        dst_relative, dst_target = _resolve_workspace_relative_path(workspace, dst)

        if src_relative == ".":
            raise WorkspaceMoveRootForbiddenError("src cannot be the workspace root")
        if dst_relative == ".":
            raise ValueError("dst must not be the workspace root")
        if src_relative == dst_relative:
            raise WorkspaceMoveSamePathError("src and dst must be different")
        if not src_target.exists():
            raise FileNotFoundError(src)

        src_type = "directory" if src_target.is_dir() else "file"
        if src_type == "directory" and _is_under(dst_target, src_target):
            raise WorkspaceMoveIntoSelfError("dst cannot be inside src")

        dst_parent = dst_target.parent
        if not dst_parent.exists():
            raise WorkspaceMoveDestinationParentMissingError(dst)
        if not dst_parent.is_dir():
            raise NotADirectoryError(dst)

        overwritten = False
        if dst_target.exists():
            if not overwrite:
                raise WorkspaceMoveDestinationExistsError(dst)
            if dst_target.is_dir():
                raise WorkspaceMoveDestinationIsDirectoryError(dst)
            if src_type == "directory":
                raise WorkspaceMoveDestinationExistsError(dst)
            overwritten = True

        await asyncio.to_thread(os.replace, src_target, dst_target)
        return {
            "session_id": session_id,
            "src": src_relative,
            "dst": dst_relative,
            "type": src_type,
            "overwritten": overwritten,
        }

    async def create_session_async(
        self,
        *,
        title: str | None = None,
        session_id: str | None = None,
        agent_type: str | None = None,
        user_id: int | None = None,
        apply_default_title: bool = True,
    ) -> dict[str, object]:
        resolved_session_id = session_id or _generate_session_id()
        resolved_agent_type = _normalize_agent_type(agent_type)
        # When apply_default_title is False we persist a NULL title so the
        # summary can still derive one from the first message — used when chat
        # implicitly creates a session just to stamp its owner.
        resolved_title = _normalize_session_title(title) if apply_default_title else title
        payload: dict[str, object] = {
            "title": resolved_title,
            "agent_type": resolved_agent_type,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        self._session_agent_types[resolved_session_id] = resolved_agent_type
        create_session = getattr(self.store, "create_session", None)
        if not callable(create_session):
            raise RuntimeError("Session store does not support create_session")
        if isinstance(self.store, AsyncSessionStore):
            result = create_session(resolved_session_id, payload)
            metadata = await result if inspect.isawaitable(result) else result
        else:
            metadata = await asyncio.to_thread(
                create_session,
                resolved_session_id,
                payload,
            )
        if self.workspace_manager is not None:
            # Seed the session's .skills/ with the owner's library (custom +
            # shared + builtin). user_id is known here, so we avoid resolving
            # ownership later in the sync per-session chatbot path.
            owner_loader = (
                self._skills_loader_for_user(user_id)
                if self.skills_loader is not None
                else None
            )
            self.workspace_manager.ensure_workspace(
                resolved_session_id,
                skills_loader=owner_loader,
            )
        return self._build_session_summary(resolved_session_id, [], metadata)

    async def rename_session_async(self, session_id: str, title: str) -> dict[str, object]:
        update_metadata = getattr(self.store, "update_session_metadata", None)
        if not callable(update_metadata):
            raise RuntimeError("Session store does not support update_session_metadata")
        payload = {"title": _normalize_session_title(title)}
        if isinstance(self.store, AsyncSessionStore):
            result = update_metadata(session_id, payload)
            metadata = await result if inspect.isawaitable(result) else result
        else:
            metadata = await asyncio.to_thread(update_metadata, session_id, payload)
        if metadata is None:
            raise KeyError(session_id)
        history = await self._load_history_async(session_id)
        return self._build_session_summary(session_id, history, metadata)

    async def load_history_async(self, session_id: str) -> list[Message]:
        return await self._load_history_async(session_id)

    async def load_session_memory_async(self, session_id: str) -> dict[str, object]:
        if self.memory_store is None:
            return {
                "session_id": session_id,
                "enabled": self._memory_enabled,
                "has_summary": False,
                "summary": "",
                "compacted_message_count": 0,
                "updated_at": None,
                "notes": [],
            }
        memory = await self.memory_store.load_memory(session_id)
        notes = await self.memory_store.list_notes(session_id)
        if memory is None:
            return {
                "session_id": session_id,
                "enabled": True,
                "has_summary": False,
                "summary": "",
                "compacted_message_count": 0,
                "updated_at": None,
                "notes": [self._serialize_memory_note(note) for note in notes],
            }
        return {
            "session_id": memory.session_id,
            "enabled": True,
            "has_summary": bool(memory.summary.strip()),
            "summary": memory.summary,
            "compacted_message_count": memory.compacted_message_count,
            "updated_at": memory.updated_at,
            "notes": [self._serialize_memory_note(note) for note in notes],
        }

    async def add_session_memory_note_async(
        self,
        session_id: str,
        *,
        content: str,
        kind: str,
    ) -> dict[str, object]:
        if self.memory_store is None:
            raise RuntimeError("session memory is not enabled")
        note = await self.memory_store.add_note(
            session_id,
            content=content,
            kind=kind,
        )
        return self._serialize_memory_note(note)

    async def archive_session_memory_note_async(
        self,
        session_id: str,
        note_id: int,
    ) -> bool:
        if self.memory_store is None:
            raise RuntimeError("session memory is not enabled")
        note = await self.memory_store.archive_note(session_id, note_id)
        return note is not None

    async def clear_session_memory_summary_async(self, session_id: str) -> dict[str, object]:
        if self.memory_store is None:
            raise RuntimeError("session memory is not enabled")
        await self.memory_store.clear_summary(session_id)
        return await self.load_session_memory_async(session_id)

    async def _load_history_async(self, session_id: str) -> list[Message]:
        if isinstance(self.store, AsyncSessionStore):
            return await self.store.load_history(session_id)
        return await asyncio.to_thread(self.store.load_history, session_id)

    async def _save_history_async(self, session_id: str, history: list[Message]) -> None:
        prepared = _prepare_history_for_persistence(history)
        if isinstance(self.store, AsyncSessionStore):
            await self.store.save_history(session_id, prepared)
            return
        await asyncio.to_thread(self.store.save_history, session_id, prepared)

    async def _load_session_metadata_async(self, session_id: str) -> dict[str, object] | None:
        get_metadata = getattr(self.store, "get_session_metadata", None)
        if not callable(get_metadata):
            return None
        if isinstance(self.store, AsyncSessionStore):
            result = get_metadata(session_id)
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(get_metadata, session_id)

    @property
    def _memory_enabled(self) -> bool:
        config = getattr(self.chatbot, "config", None)
        return bool(getattr(config, "memory_enabled", False))

    async def _prepare_memory_context_async(
        self,
        session_id: str,
        message: MessageContent,
        *,
        history: list[Message],
        injected: list[Message],
        model_override: str | None,
        system_prompt_override: str | None,
        max_tokens_override: int | None,
        on_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> _PreparedMemoryContext:
        if not self._memory_enabled or self.memory_store is None:
            return _PreparedMemoryContext(
                history=[*history, *injected],
                system_prompt_override=system_prompt_override,
                compacted_message_count=0,
                runtime_notices=[],
            )

        memory = await self.memory_store.load_memory(session_id)
        notes = await self.memory_store.list_notes(session_id)
        compacted_count = self._clamp_compacted_message_count(memory, history)
        summary = memory.summary if memory is not None else ""
        chatbot = self._get_chatbot_for_session(session_id)
        base_prompt = self._resolve_base_system_prompt(chatbot, system_prompt_override)
        prompt_with_memory = self._build_memory_augmented_prompt(base_prompt, summary, notes)
        has_memory_context = self._memory_context_available(summary, notes)
        live_history = [*history[compacted_count:], *injected]
        budget = self._memory_input_budget(max_tokens_override)
        estimated = self._estimate_memory_prompt_tokens(prompt_with_memory, live_history, message)

        if estimated <= budget:
            _emit_runtime_event(
                on_event,
                "memory_compaction_skipped",
                {
                    "session_id": session_id,
                    "reason": "within_budget",
                    "estimated_tokens": estimated,
                    "budget_tokens": budget,
                },
            )
            return _PreparedMemoryContext(
                history=live_history,
                system_prompt_override=prompt_with_memory if has_memory_context else system_prompt_override,
                compacted_message_count=compacted_count,
                runtime_notices=[],
            )

        target = max(1, int(budget * self._memory_compression_ratio))
        _emit_runtime_event(
            on_event,
            "memory_compaction_started",
            {
                "session_id": session_id,
                "reason": "prompt_budget_exceeded",
                "estimated_tokens": estimated,
                "budget_tokens": budget,
                "target_tokens": target,
                "compacted_message_count_before": compacted_count,
            },
        )

        try:
            chunk, next_count = self._pick_memory_compaction_chunk(
                history,
                compacted_count=compacted_count,
                injected=injected,
                current_message=message,
                system_prompt=prompt_with_memory,
                target_tokens=target,
            )
            if not chunk:
                _emit_runtime_event(
                    on_event,
                    "memory_compaction_skipped",
                    {
                        "session_id": session_id,
                        "reason": "no_compactable_turns",
                        "estimated_tokens": estimated,
                        "budget_tokens": budget,
                    },
                )
                return _PreparedMemoryContext(
                    history=live_history,
                    system_prompt_override=prompt_with_memory if has_memory_context else system_prompt_override,
                    compacted_message_count=compacted_count,
                    runtime_notices=[
                        self._build_runtime_notice(
                            kind="warning",
                            text="上下文接近上限，但目前沒有可再整理的較早對話",
                        ),
                    ],
                )

            summary = await self._generate_memory_summary_async(
                chatbot,
                session_id=session_id,
                existing_summary=summary,
                chunk=chunk,
                model_override=model_override,
                on_event=on_event,
            )
            memory = await self.memory_store.save_memory(
                session_id,
                summary=summary,
                compacted_message_count=next_count,
            )
            prompt_with_memory = self._build_memory_augmented_prompt(base_prompt, memory.summary, notes)
            live_history = [*history[memory.compacted_message_count:], *injected]
            _emit_runtime_event(
                on_event,
                "memory_compaction_finished",
                {
                    "session_id": session_id,
                    "compacted_message_count_before": compacted_count,
                    "compacted_message_count_after": memory.compacted_message_count,
                    "summary_chars": len(memory.summary),
                    "summary_updated": True,
                },
            )
            return _PreparedMemoryContext(
                history=live_history,
                system_prompt_override=prompt_with_memory,
                compacted_message_count=memory.compacted_message_count,
                runtime_notices=[
                    self._build_runtime_notice(
                        kind="success",
                        text=(
                            "已整理較早對話，後續會以摘要延續上下文"
                            + (
                                f"（本次整理 {max(0, memory.compacted_message_count - compacted_count)} 則）"
                                if memory.compacted_message_count > compacted_count
                                else ""
                            )
                        ),
                    ),
                ],
            )
        except Exception as exc:
            _emit_runtime_event(
                on_event,
                "memory_compaction_failed",
                {
                    "session_id": session_id,
                    "message": "memory compaction failed",
                    "error": str(exc),
                },
            )
            return _PreparedMemoryContext(
                history=live_history,
                system_prompt_override=prompt_with_memory if has_memory_context else system_prompt_override,
                compacted_message_count=compacted_count,
                runtime_notices=[
                    self._build_runtime_notice(
                        kind="error",
                        text=(
                            "整理較早對話失敗，已改用原始上下文繼續"
                            + (f"：{exc}" if str(exc) else "")
                        ),
                    ),
                ],
            )

    def _resolve_base_system_prompt(
        self,
        chatbot: Any,
        system_prompt_override: str | None,
    ) -> str:
        if system_prompt_override is not None and system_prompt_override.strip():
            return system_prompt_override.strip()
        prompt = getattr(chatbot, "system_prompt", None)
        return prompt if isinstance(prompt, str) else ""

    @staticmethod
    def _build_runtime_notice(*, kind: str, text: str) -> dict[str, str]:
        return {
            "key": "memory",
            "kind": kind,
            "text": text,
        }

    @staticmethod
    def _build_memory_augmented_prompt(
        base_prompt: str,
        summary: str,
        notes: list[SessionMemoryNoteRow],
    ) -> str:
        cleaned = summary.strip()
        cleaned_notes = [note for note in notes if note.content.strip()]
        if (not cleaned or cleaned == "(nothing)") and not cleaned_notes:
            return base_prompt
        sections: list[str] = []
        if cleaned and cleaned != "(nothing)":
            sections.append(
                "# Session Memory Summary\n\n"
                "The following is a compact summary of earlier turns in this session. "
                "Use it as continuity context; prefer current user instructions when they conflict.\n\n"
                f"{cleaned}",
            )
        if cleaned_notes:
            sections.append(
                "# User Memory Notes\n\n"
                "These notes were explicitly added or corrected by the user. "
                "Treat them as high-priority session preferences or facts unless the current user message supersedes them.\n\n"
                f"{LocalAgentRuntime._format_memory_notes_for_prompt(cleaned_notes)}",
            )
        return f"{base_prompt}\n\n---\n\n" + "\n\n".join(sections)

    @staticmethod
    def _memory_context_available(summary: str, notes: list[SessionMemoryNoteRow]) -> bool:
        if summary.strip() and summary.strip() != "(nothing)":
            return True
        return any(note.content.strip() for note in notes)

    @staticmethod
    def _format_memory_notes_for_prompt(notes: list[SessionMemoryNoteRow]) -> str:
        label_map = {
            "note": "Note",
            "preference": "Preference",
            "correction": "Correction",
        }
        return "\n".join(
            f"- {label_map.get(note.kind, 'Note')}: {note.content.strip()}"
            for note in notes
            if note.content.strip()
        )

    @staticmethod
    def _serialize_memory_note(note: SessionMemoryNoteRow) -> dict[str, object]:
        return {
            "id": note.id,
            "session_id": note.session_id,
            "kind": note.kind,
            "content": note.content,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        }

    def _memory_input_budget(self, max_tokens_override: int | None) -> int:
        config = getattr(self.chatbot, "config", None)
        context_window = int(getattr(config, "context_window_tokens", 0) or 0)
        output_tokens = int(
            max_tokens_override
            if max_tokens_override is not None
            else getattr(config, "max_tokens", 0) or 0
        )
        return max(1, context_window - output_tokens - _MEMORY_TRIM_SAFETY_BUFFER_TOKENS)

    @property
    def _memory_compression_ratio(self) -> float:
        config = getattr(self.chatbot, "config", None)
        return float(getattr(config, "memory_compression_ratio", 0.5) or 0.5)

    @staticmethod
    def _estimate_memory_prompt_tokens(
        system_prompt: str,
        history: list[Message],
        current_message: MessageContent,
    ) -> int:
        probe = [*history, {"role": "user", "content": current_message}]
        return AgentLoop._estimate_prompt_tokens(system_prompt, probe)

    @staticmethod
    def _clamp_compacted_message_count(
        memory: SessionMemoryRow | None,
        history: list[Message],
    ) -> int:
        if memory is None:
            return 0
        return min(max(0, memory.compacted_message_count), len(history))

    def _pick_memory_compaction_chunk(
        self,
        history: list[Message],
        *,
        compacted_count: int,
        injected: list[Message],
        current_message: MessageContent,
        system_prompt: str,
        target_tokens: int,
    ) -> tuple[list[Message], int]:
        live = history[compacted_count:]
        turns = AgentLoop._group_conversation_turns(live)
        if len(turns) <= 1:
            return [], compacted_count

        removed_turns: list[list[Message]] = []
        remaining_turns = list(turns)
        while len(remaining_turns) > 1:
            removed_turns.append(remaining_turns.pop(0))
            remaining = [*AgentLoop._flatten_turns(remaining_turns), *injected]
            estimated = self._estimate_memory_prompt_tokens(
                system_prompt,
                remaining,
                current_message,
            )
            if estimated <= target_tokens:
                break

        chunk = AgentLoop._flatten_turns(removed_turns)
        return chunk, compacted_count + len(chunk)

    async def _generate_memory_summary_async(
        self,
        chatbot: Any,
        *,
        session_id: str,
        existing_summary: str,
        chunk: list[Message],
        model_override: str | None,
        on_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> str:
        provider = getattr(chatbot, "provider", None)
        config = getattr(chatbot, "config", None)
        if provider is None or config is None:
            raise RuntimeError("memory compaction requires a SimplifiedChatbot provider")

        prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "memory_summary.md"
        system_prompt = prompt_path.read_text(encoding="utf-8").strip()
        user_prompt = (
            "## Existing Session Memory\n"
            f"{existing_summary.strip() or '(empty)'}\n\n"
            "## Conversation Turns To Absorb\n"
            f"{self._format_messages_for_memory(chunk)}"
        )
        model = model_override or getattr(config, "model")
        t0 = datetime.now(timezone.utc)
        response = await provider.generate_async(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            max_tokens=min(_MEMORY_SUMMARY_MAX_TOKENS, int(getattr(config, "max_tokens", 1024))),
            temperature=0.0,
            timeout=float(getattr(config, "request_timeout", 120.0)),
            tools=None,
        )
        latency_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        _emit_runtime_event(
            on_event,
            "llm_call_finished",
            {
                "model": model,
                "latency_ms": latency_ms,
                "ttft_ms": None,
                "success": True,
                "error_type": None,
                "purpose": "memory_compaction",
            },
        )
        summary = (response.content or "").strip()
        if not summary:
            raise RuntimeError("memory compaction returned an empty summary")
        if summary == "(nothing)" and existing_summary.strip():
            raise RuntimeError("memory compaction did not absorb new context")
        return summary

    @staticmethod
    def _format_messages_for_memory(messages: list[Message]) -> str:
        lines: list[str] = []
        for message in messages:
            role = str(message.get("role", "unknown")).upper()
            content = AgentLoop._stringify_message_content(message.get("content", ""))
            if not content:
                continue
            lines.append(f"{role}: {content}")
            if isinstance(message.get("tool_calls"), list):
                lines.append(
                    "TOOL_CALLS: "
                    + json.dumps(message["tool_calls"], ensure_ascii=False)
                )
        return "\n".join(lines) or "(empty)"

    @staticmethod
    def _restore_full_history_after_memory(
        original_history: list[Message],
        result_messages: list[Message],
        compacted_message_count: int,
    ) -> list[Message]:
        if compacted_message_count <= 0:
            return result_messages
        prefix = original_history[: min(compacted_message_count, len(original_history))]
        return [*prefix, *result_messages]

    @staticmethod
    def _attach_runtime_notices(
        messages: list[Message],
        notices: list[dict[str, str]],
    ) -> list[Message]:
        if not notices:
            return messages
        attached = [dict(message) for message in messages]
        for index in range(len(attached) - 1, -1, -1):
            message = attached[index]
            if message.get("role") != "assistant":
                continue
            metadata = dict(message.get("metadata") or {})
            existing_raw = metadata.get("runtime_notices")
            existing: list[dict[str, str]] = []
            if isinstance(existing_raw, list):
                for item in existing_raw:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("key")
                    kind = item.get("kind")
                    text = item.get("text")
                    if (
                        isinstance(key, str)
                        and isinstance(kind, str)
                        and isinstance(text, str)
                    ):
                        existing.append({"key": key, "kind": kind, "text": text})
            by_key = {item["key"]: item for item in existing}
            for notice in notices:
                by_key[notice["key"]] = dict(notice)
            metadata["runtime_notices"] = list(by_key.values())
            message["metadata"] = metadata
            attached[index] = message
            return attached
        return attached

    async def _run_chat_async(
        self,
        session_id: str,
        message: MessageContent,
        history: list[Message],
        model_override: str | None,
        on_event: Callable[[str, dict[str, Any]], None] | None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_async = getattr(chatbot, "run_async", None)
        if callable(run_async):
            result = _invoke_chatbot_method(
                run_async,
                message,
                history=history,
                model_override=model_override,
                temperature_override=temperature_override,
                max_tokens_override=max_tokens_override,
                max_iterations_override=max_iterations_override,
                system_prompt_override=system_prompt_override,
                disabled_tools=disabled_tools,
                on_event=on_event,
            )
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(
            chatbot.run,
            message,
            history=history,
            model_override=model_override,
        )

    async def _run_chat_stream_async(
        self,
        session_id: str,
        message: MessageContent,
        *,
        history: list[Message],
        on_delta: Callable[[str], None] | None,
        model_override: str | None,
        on_event: Callable[[str, dict[str, Any]], None] | None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_stream_async = getattr(chatbot, "run_stream_async", None)
        if callable(run_stream_async):
            result = _invoke_chatbot_method(
                run_stream_async,
                message,
                history=history,
                on_delta=on_delta,
                model_override=model_override,
                temperature_override=temperature_override,
                max_tokens_override=max_tokens_override,
                max_iterations_override=max_iterations_override,
                system_prompt_override=system_prompt_override,
                disabled_tools=disabled_tools,
                on_event=on_event,
            )
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(
            chatbot.run_stream,
            message,
            history,
            on_delta=on_delta,
            model_override=model_override,
        )

    async def _continue_chat_async(
        self,
        session_id: str,
        *,
        history: list[Message],
        model_override: str | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        continue_stream_async = getattr(chatbot, "continue_stream_async", None)
        if callable(continue_stream_async):
            result = continue_stream_async(
                history,
                on_delta=on_delta,
                model_override=model_override,
                on_event=on_event,
            )
        else:
            continue_async = getattr(chatbot, "continue_async", None)
            if not callable(continue_async):
                raise RuntimeError("Chatbot does not support continue_async(...)")
            result = continue_async(
                history,
                model_override=model_override,
                on_event=on_event,
            )
        if inspect.isawaitable(result):
            return await result
        return result

    async def _prime_session_agent_type_async(self, session_id: str) -> str | None:
        """Resolve and cache the agent type for a session from persisted metadata."""
        if session_id in self._session_agent_types:
            return self._session_agent_types[session_id]
        metadata = await self._load_session_metadata_async(session_id)
        agent_type = _normalize_agent_type(
            metadata.get("agent_type") if isinstance(metadata, dict) else None,
        )
        self._session_agent_types[session_id] = agent_type
        return agent_type

    def _get_chatbot_for_session(self, session_id: str) -> Any:
        if not isinstance(self.chatbot, SimplifiedChatbot):
            return self.chatbot
        if not self.chatbot.supports_workspace_clone:
            return self.chatbot

        cached = self._session_chatbots.get(session_id)
        if cached is not None:
            return cached

        if self.workspace_manager is not None:
            workspace = self.workspace_manager.ensure_workspace(session_id)
        else:
            workspace = self.chatbot.default_workspace or Path.cwd()
        session_chatbot = self.chatbot.for_workspace(
            workspace,
            session_id=session_id,
            agent_type=self._session_agent_types.get(session_id),
        )
        self._bind_chrome_port(session_chatbot)
        self._bind_subagent_tools(session_chatbot)
        self._session_chatbots[session_id] = session_chatbot
        return session_chatbot

    def _bind_subagent_manager_callback(self) -> None:
        manager = getattr(self.chatbot, "subagent_manager", None)
        bind_spawn_callback = getattr(manager, "bind_spawn_callback", None)
        if callable(bind_spawn_callback):
            bind_spawn_callback(self._handle_subagent_spawn)
        bind_event_callback = getattr(manager, "bind_event_callback", None)
        if callable(bind_event_callback):
            bind_event_callback(self._handle_subagent_event)
        bind_callback = getattr(manager, "bind_result_callback", None)
        if callable(bind_callback):
            bind_callback(self._handle_subagent_result)

    def _bind_subagent_tools(self, chatbot: Any) -> None:
        tools = getattr(chatbot, "tools", None)
        if tools is None or self.subagent_store is None:
            return
        for tool_name in ("list_subagents", "subagent_wait"):
            tool = tools.get(tool_name) if hasattr(tools, "get") else None
            bind_store = getattr(tool, "bind_store", None)
            if callable(bind_store):
                bind_store(self.subagent_store)

    def _refresh_mcp_tool_registries(self) -> None:
        manager = self.mcp_manager
        if manager is None:
            return
        chatbots = [self.chatbot, *self._session_chatbots.values()]
        seen: set[int] = set()
        for chatbot in chatbots:
            if chatbot is None:
                continue
            tools = getattr(chatbot, "tools", None)
            if tools is None:
                continue
            marker = id(tools)
            if marker in seen:
                continue
            seen.add(marker)
            register = getattr(manager, "register_tools_into", None)
            if callable(register):
                register(tools, profile=None)

    def _iter_exec_session_managers(
        self,
        session_id: str,
    ) -> list[Any]:
        managers: list[Any] = []
        seen: set[int] = set()
        chatbots = [self._session_chatbots.get(session_id), self.chatbot]
        for chatbot in chatbots:
            if chatbot is None:
                continue
            tools = getattr(chatbot, "tools", None)
            if tools is None or not hasattr(tools, "get"):
                continue
            for tool_name in ("exec", "write_stdin", "list_exec_sessions"):
                tool = tools.get(tool_name)
                manager = getattr(tool, "session_manager", None)
                if manager is None:
                    continue
                marker = id(manager)
                if marker in seen:
                    continue
                seen.add(marker)
                managers.append(manager)
        return managers

    def _terminate_exec_sessions_for_session(self, session_id: str) -> None:
        for manager in self._iter_exec_session_managers(session_id):
            terminate_sync = getattr(manager, "terminate_owner_sessions_sync", None)
            if callable(terminate_sync):
                terminate_sync(session_id)

    async def _terminate_exec_sessions_for_session_async(self, session_id: str) -> None:
        for manager in self._iter_exec_session_managers(session_id):
            terminate = getattr(manager, "terminate_owner_sessions", None)
            if callable(terminate):
                await terminate(session_id)

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    def subscribe_session_events(
        self,
        session_id: str,
    ) -> _SessionEventSubscriberQueue:
        queue = _SessionEventSubscriberQueue(
            max_size=_SESSION_EVENT_SUBSCRIBER_QUEUE_MAX_SIZE,
        )
        subscribers = self._session_event_subscribers.setdefault(session_id, [])
        subscribers.append(queue)
        return queue

    def unsubscribe_session_events(
        self,
        session_id: str,
        queue: _SessionEventSubscriberQueue,
    ) -> None:
        subscribers = self._session_event_subscribers.get(session_id)
        if not subscribers:
            return
        try:
            subscribers.remove(queue)
        except ValueError:
            return
        if not subscribers:
            self._session_event_subscribers.pop(session_id, None)

    def publish_session_event(
        self,
        session_id: str,
        event_payload: dict[str, object],
    ) -> int:
        subscribers = self._session_event_subscribers.get(session_id, [])
        delivered = 0
        for queue in list(subscribers):
            queue.put_nowait(dict(event_payload))
            delivered += 1
        return delivered

    async def _run_with_session_lock(
        self,
        session_id: str,
        runner: Callable[[], Any],
    ) -> Any:
        async with self._get_session_lock(session_id):
            await self._prime_session_agent_type_async(session_id)
            result = runner()
            if inspect.isawaitable(result):
                return await result
            return result

    def _enqueue_internal_message(self, session_id: str, message: Message) -> int:
        queue = self._pending_internal_messages.setdefault(session_id, [])
        queue.append(dict(message))
        return len(queue)

    def _pop_pending_internal_messages(self, session_id: str) -> list[Message]:
        items = self._pending_internal_messages.pop(session_id, [])
        return [dict(item) for item in items]

    def _peek_pending_internal_messages(self, session_id: str) -> list[Message]:
        items = self._pending_internal_messages.get(session_id, [])
        return [dict(item) for item in items]

    def _schedule_background_session_task(
        self,
        session_id: str,
        task_factory: Callable[[], Any],
    ) -> bool:
        existing = self._background_tasks.get(session_id)
        if existing is not None and not existing.done():
            return False
        if session_id in self._resume_requested:
            return False

        self._resume_requested.add(session_id)

        async def run_background() -> None:
            try:
                result = task_factory()
                if inspect.isawaitable(result):
                    await result
            finally:
                self._resume_requested.discard(session_id)

        task = asyncio.create_task(
            run_background(),
            name=f"runtime-background:{session_id}",
        )
        self._background_tasks[session_id] = task
        task.add_done_callback(
            lambda finished, sid=session_id: self._cleanup_background_task(sid, finished),
        )
        return True

    def _cleanup_background_task(
        self,
        session_id: str,
        task: asyncio.Task[None],
    ) -> None:
        if not task.cancelled():
            try:
                task.exception()
            except Exception:
                pass
        current = self._background_tasks.get(session_id)
        if current is task:
            self._background_tasks.pop(session_id, None)

    def _restore_pending_internal_messages(
        self,
        session_id: str,
        messages: list[Message],
    ) -> None:
        if not messages:
            return
        queue = self._pending_internal_messages.setdefault(session_id, [])
        queue[:0] = [dict(item) for item in messages]

    async def _handle_subagent_spawn(self, status) -> None:
        await self._persist_subagent_spawn(status)

    async def _handle_subagent_event(self, status, event: str, payload: dict[str, Any]) -> None:
        session_id = getattr(status, "parent_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        task_id = getattr(status, "task_id", None)
        if not isinstance(task_id, str) or not task_id.strip():
            return
        persisted_event = await self._persist_subagent_event(status, event, payload)
        seq = (
            int(persisted_event["seq"])
            if persisted_event is not None and "seq" in persisted_event
            else self._next_subagent_event_seq(task_id)
        )
        created_at = (
            str(persisted_event["created_at"])
            if persisted_event is not None and "created_at" in persisted_event
            else _utc_timestamp()
        )
        queue = self._recent_subagent_events.setdefault(session_id, [])
        queue.append(
            {
                "session_id": session_id,
                "task_id": task_id,
                "label": getattr(status, "label", None),
                "event": event,
                "data": dict(payload),
                "seq": seq,
                "created_at": created_at,
            },
        )
        self.publish_session_event(session_id, queue[-1])
        if len(queue) > 200:
            del queue[:-200]

        # Emit workspace_changed so the file tree refreshes after subagent file ops.
        # tool_call_finished payloads include "name", so we can check directly.
        if event == "subagent_tool_call_finished" and payload.get("ok") is True:
            paths = _workspace_change_paths(payload)
            if paths is not None:
                self.publish_session_event(
                    session_id,
                    {
                        "session_id": session_id,
                        "event": "workspace_changed",
                        "data": {"session_id": session_id, "paths": paths},
                    },
                )

    def _next_subagent_event_seq(self, task_id: str) -> int:
        next_seq = self._subagent_event_seq.get(task_id, 0) + 1
        self._subagent_event_seq[task_id] = next_seq
        return next_seq

    async def _handle_subagent_result(self, status, result) -> None:
        await self._persist_subagent_result(status, result)
        session_id = getattr(status, "parent_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        self._enqueue_internal_message(
            session_id,
            self._build_subagent_internal_message(status, result),
        )
        self._schedule_background_session_task(
            session_id,
            lambda: self._drain_auto_resume_loop(session_id),
        )

    async def _drain_auto_resume_loop(self, session_id: str) -> None:
        while True:
            processed = await self._continue_session_from_internal_messages(session_id)
            if not processed:
                return

    async def _continue_session_from_internal_messages(self, session_id: str) -> bool:
        async def runner() -> bool:
            history = await self._load_history_async(session_id)
            injected = self._pop_pending_internal_messages(session_id)
            if not injected:
                return False
            effective_history = [*history, *injected]
            run_id = f"resume_{uuid.uuid4().hex[:12]}"
            self._publish_auto_resume_event(
                session_id,
                run_id,
                "assistant_started",
                {"trigger": "subagent_result"},
            )

            def on_delta(delta: str) -> None:
                if not delta:
                    return
                self._publish_auto_resume_event(
                    session_id,
                    run_id,
                    "assistant_delta",
                    {"delta": delta},
                )

            def on_event(event: str, data: dict[str, Any]) -> None:
                self._publish_auto_resume_event(
                    session_id,
                    run_id,
                    f"assistant_{event}",
                    dict(data) if isinstance(data, dict) else {"value": data},
                )

            try:
                result = await self._continue_chat_async(
                    session_id,
                    history=effective_history,
                    model_override=None,
                    on_delta=on_delta,
                    on_event=on_event,
                )
            except Exception as exc:
                self._restore_pending_internal_messages(session_id, injected)
                self._publish_auto_resume_event(
                    session_id,
                    run_id,
                    "assistant_error",
                    {"message": str(exc)},
                )
                raise
            await self._save_history_async(
                session_id,
                _stamp_run_id(result.messages, len(effective_history), run_id),
            )
            self._publish_auto_resume_event(
                session_id,
                run_id,
                "assistant_done",
                {
                    "content": getattr(result, "content", "") or "",
                    "stop_reason": getattr(result, "stop_reason", "stop"),
                    "usage": dict(getattr(result, "usage", {}) or {}),
                    "tools_used": list(getattr(result, "tools_used", []) or []),
                },
            )
            return True

        return await self._run_with_session_lock(session_id, runner)

    def _publish_auto_resume_event(
        self,
        session_id: str,
        run_id: str,
        event: str,
        data: dict[str, Any],
    ) -> None:
        self.publish_session_event(
            session_id,
            {
                "session_id": session_id,
                "run_id": run_id,
                "event": event,
                "data": data,
                "created_at": _utc_timestamp(),
            },
        )

    @staticmethod
    def _build_subagent_internal_message(status, result) -> Message:
        workspace = getattr(result, "workspace", None) or getattr(status, "workspace", None)
        workspace_text = str(workspace) if workspace is not None else "(unknown)"
        label = getattr(status, "label", "") or getattr(result, "task_id", "subagent")
        task = getattr(status, "task", "")
        stop_reason = getattr(result, "stop_reason", "unknown")
        content = "\n".join(
            [
                f"Subagent [{label}] has finished.",
                "",
                "Task:",
                task,
                "",
                "Outcome:",
                f"- status: {stop_reason}",
                f"- workspace: {workspace_text}",
                "",
                "Result:",
                getattr(result, "content", "") or "(no result content)",
                "",
                "Use this result as internal work output for the same session. Summarize or continue the task as appropriate.",
            ]
        )
        # Injected as a synthetic `user` turn (not `system`): the auto-resume
        # appends this to the end of the conversation, and OpenAI-compatible
        # models return empty content when the final message is a system turn
        # (there is no user/tool turn to answer). The `metadata.internal` /
        # `kind: subagent_result` markers let the frontend render it as a card
        # rather than a user bubble.
        return {
            "role": "user",
            "content": content,
            "metadata": {
                "internal": True,
                "source": "subagent",
                "kind": "subagent_result",
                "task_id": getattr(status, "task_id", None),
                "parent_session_id": getattr(status, "parent_session_id", None),
                "ok": getattr(result, "ok", None),
                "stop_reason": stop_reason,
            },
        }

    async def _persist_subagent_spawn(self, status) -> None:
        if self.subagent_store is None:
            return
        session_id = getattr(status, "parent_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        await self.subagent_store.upsert_run(
            {
                "task_id": getattr(status, "task_id"),
                "parent_session_id": session_id,
                "label": getattr(status, "label"),
                "task": getattr(status, "task"),
                "workspace": getattr(status, "workspace", None),
                "phase": getattr(status, "phase", "initializing"),
                "started_at": getattr(status, "started_at_utc", _utc_timestamp()),
                "finished_at": None,
                "stop_reason": getattr(status, "stop_reason", None),
                "ok": None,
                "error": getattr(status, "error", None),
                "usage": dict(getattr(status, "usage", {}) or {}),
                "tool_events": list(getattr(status, "tool_events", []) or []),
                "final_content": None,
                "model": getattr(status, "model", None),
            },
        )

    async def _persist_subagent_result(self, status, result) -> None:
        if self.subagent_store is None:
            return
        session_id = getattr(status, "parent_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return
        await self.subagent_store.upsert_run(
            {
                "task_id": getattr(status, "task_id"),
                "parent_session_id": session_id,
                "label": getattr(status, "label"),
                "task": getattr(status, "task"),
                "workspace": getattr(result, "workspace", None) or getattr(status, "workspace", None),
                "phase": getattr(status, "phase", getattr(result, "stop_reason", "done")),
                "started_at": getattr(status, "started_at_utc", _utc_timestamp()),
                "finished_at": _utc_timestamp(),
                "stop_reason": getattr(result, "stop_reason", None),
                "ok": getattr(result, "ok", None),
                "error": getattr(result, "error", None) or getattr(status, "error", None),
                "usage": dict(getattr(result, "usage", {}) or {}),
                "tool_events": list(getattr(result, "tool_events", []) or []),
                "final_content": getattr(result, "content", None),
                "model": getattr(status, "model", None),
            },
        )

    async def _persist_subagent_event(
        self,
        status,
        event: str,
        payload: dict[str, Any],
    ) -> dict[str, object] | None:
        if self.subagent_event_store is None:
            return None
        session_id = getattr(status, "parent_session_id", None)
        if not isinstance(session_id, str) or not session_id.strip():
            return None
        task_id = getattr(status, "task_id", None)
        if not isinstance(task_id, str) or not task_id.strip():
            return None
        return await self.subagent_event_store.append_event(
            task_id=task_id,
            parent_session_id=session_id,
            event_type=event,
            payload={
                "label": getattr(status, "label", None),
                "data": dict(payload),
            },
        )

    @contextmanager
    def _apply_subagent_model_override(
        self,
        session_id: str,
        subagent_model: str | None,
    ):
        spawn_tool = self._get_spawn_tool_for_session(session_id)
        previous: str | None = None
        if spawn_tool is not None:
            previous = getattr(spawn_tool, "_default_model", None)
            if subagent_model is not None:
                spawn_tool.set_default_model(subagent_model)
        try:
            yield
        finally:
            if spawn_tool is not None and subagent_model is not None:
                spawn_tool.set_default_model(previous)

    def _get_spawn_tool_for_session(self, session_id: str) -> Any | None:
        chatbot = self._get_chatbot_for_session(session_id)
        tools = getattr(chatbot, "tools", None)
        if tools is None or not hasattr(tools, "get"):
            return None
        return tools.get("spawn")

    def _resolve_model_override(self, model_override: str | None) -> str | None:
        if model_override is None:
            return None
        stripped = model_override.strip()
        if not stripped:
            raise ValueError("model_override must not be empty")

        config = getattr(self.chatbot, "config", None)
        available_models = getattr(config, "available_models", []) if config is not None else []
        if available_models:
            allowed = [item for item in available_models if isinstance(item, str) and item]
        else:
            default_model = getattr(config, "model", None) if config is not None else None
            allowed = [default_model] if isinstance(default_model, str) and default_model else []

        if allowed and stripped not in allowed:
            raise ModelNotAllowedError(
                f"Model '{stripped}' is not in the configured available models",
            )
        return stripped

    @staticmethod
    def _build_session_summary(
        session_id: str,
        history: list[Message],
        metadata: dict[str, object] | None,
    ) -> dict[str, object]:
        first_user = next(
            (
                _content_to_preview_text(message["content"])
                for message in history
                if message.get("role") == "user"
                and _content_to_preview_text(message.get("content", "")).strip()
            ),
            "",
        )
        last_user = next(
            (
                _content_to_preview_text(message["content"])
                for message in reversed(history)
                if message.get("role") == "user"
                and _content_to_preview_text(message.get("content", "")).strip()
            ),
            "",
        )
        last_assistant = next(
            (
                _content_to_preview_text(message["content"])
                for message in reversed(history)
                if message.get("role") == "assistant"
                and _content_to_preview_text(message.get("content", "")).strip()
            ),
            "",
        )
        session_metadata = metadata or {}
        created_at = session_metadata.get("created_at")
        updated_at = session_metadata.get("updated_at")
        title = session_metadata.get("title")
        agent_type = session_metadata.get("agent_type")
        user_id = session_metadata.get("user_id")
        return {
            "session_id": session_id,
            "title": (
                str(title)
                if isinstance(title, str) and title.strip()
                else _derive_session_title(first_user, session_id=session_id)
            ),
            "agent_type": agent_type if isinstance(agent_type, str) else None,
            "user_id": user_id if isinstance(user_id, int) else None,
            "created_at": created_at if isinstance(created_at, str) else None,
            "updated_at": updated_at if isinstance(updated_at, str) else None,
            "message_count": sum(
                1
                for message in history
                if message.get("role") in {"user", "assistant"}
            ),
            "last_user_message": _preview_text(last_user),
            "last_assistant_preview": _preview_text(last_assistant),
        }
        
    async def answer_ask_user_question(
        self,
        session_id: str,
        answers: dict[str, Any],
    ) -> bool:
        """Deliver user answers to a pending ask_user_question tool call.

        Returns True if a pending question was found and resolved.
        """
        from simplified_chatbot.tools.ask_user_question import AskUserQuestionTool

        chatbot = self._get_chatbot_for_session(session_id)
        tools = getattr(chatbot, "tools", None)
        if tools is None or not hasattr(tools, "get"):
            return False
        tool = tools.get("ask_user_question")
        if not isinstance(tool, AskUserQuestionTool):
            return False
        return tool.answer(answers)

    def _bind_chrome_port(self, session_chatbot: Any) -> None:
        if self.chrome_debugging_port is None:
            return
        tools = getattr(session_chatbot, "tools", None)
        if tools is None:
            return
        exec_tool = tools.get("exec") if hasattr(tools, "get") else None
        if isinstance(exec_tool, ExecTool):
            exec_tool.bind_chrome_debugging_port(self.chrome_debugging_port)

def _resolve_workspace_root_dir(
    *,
    config_file: Path | None,
    configured_workspace_root: str | None,
    override_workspace_root: str | Path | None,
) -> Path:
    candidate = override_workspace_root
    if candidate is None:
        candidate = configured_workspace_root
    if candidate is None:
        candidate = "workspaces"

    path = Path(candidate).expanduser()
    if not path.is_absolute():
        if config_file is not None:
            path = config_file.parent / path
        else:
            path = Path.cwd() / path
    return path.resolve()


def _build_default_subagent_store(
    store: SessionStore | AsyncSessionStore | None,
) -> AioSQLiteSubagentStore | None:
    if isinstance(store, AioSQLiteSessionStore):
        return AioSQLiteSubagentStore(store.db_path)
    return None


def _build_default_subagent_event_store(
    store: SessionStore | AsyncSessionStore | None,
) -> AioSQLiteSubagentEventStore | None:
    if isinstance(store, AioSQLiteSessionStore):
        return AioSQLiteSubagentEventStore(store.db_path)
    return None


def _resolve_workspace_relative_path(workspace: Path, raw_path: str | None) -> tuple[str, Path]:
    candidate = Path(raw_path or ".")
    if candidate.is_absolute():
        raise ValueError("path must be relative to the session workspace")
    resolved = (workspace / candidate).resolve()
    try:
        relative = resolved.relative_to(workspace.resolve())
    except ValueError as exc:
        raise ValueError("path is outside the session workspace") from exc
    return ("." if str(relative) == "." else relative.as_posix()), resolved


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_under(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


@dataclass(slots=True)
class UploadFileInput:
    """Runtime-friendly uploaded file payload decoupled from FastAPI."""

    name: str
    content: bytes
    content_type: str | None = None
    # POSIX relative path from the upload root, e.g. "subdir/file.txt".
    # When set, the file is placed at <target_dir>/<relative_path> and
    # intermediate directories are created automatically.
    relative_path: str | None = None


class WorkspaceUploadError(ValueError):
    """Base error for workspace upload validation failures."""


class WorkspaceUploadNoFilesError(WorkspaceUploadError):
    """Raised when no files are provided."""


class WorkspaceUploadTooManyFilesError(WorkspaceUploadError):
    """Raised when one request exceeds the file count limit."""


class WorkspaceUploadFileTooLargeError(WorkspaceUploadError):
    """Raised when one uploaded file exceeds the size limit."""


class WorkspaceFilenameInvalidError(WorkspaceUploadError):
    """Raised when an uploaded filename is invalid."""


class WorkspaceMoveError(ValueError):
    """Base error for workspace move validation failures."""


class WorkspaceMoveDestinationExistsError(WorkspaceMoveError):
    """Raised when move destination already exists and overwrite is false."""


class WorkspaceMoveDestinationIsDirectoryError(WorkspaceMoveError):
    """Raised when overwrite targets an existing directory."""


class WorkspaceMoveSamePathError(WorkspaceMoveError):
    """Raised when src and dst resolve to the same path."""


class WorkspaceMoveRootForbiddenError(WorkspaceMoveError):
    """Raised when src is the workspace root."""


class WorkspaceMoveIntoSelfError(WorkspaceMoveError):
    """Raised when moving a directory into itself."""


class WorkspaceMoveDestinationParentMissingError(WorkspaceMoveError):
    """Raised when the destination parent directory does not exist."""


class WorkspaceFileAlreadyExistsError(ValueError):
    """Raised when creating a file that already exists and overwrite is false."""


class WorkspaceDirectoryNotEmptyError(ValueError):
    """Raised when deleting a non-empty directory without recursive=True."""


class WorkspaceDeleteRootForbiddenError(ValueError):
    """Raised when trying to delete the workspace root directory."""


class ModelNotAllowedError(ValueError):
    """Raised when a requested model is outside the configured allowlist."""


def _emit_runtime_event(
    callback: Callable[[str, dict[str, Any]], None] | None,
    event: str,
    data: dict[str, Any],
) -> None:
    if callback is not None:
        callback(event, data)


def _build_runtime_event_callback(
    session_id: str,
    callback: Callable[[str, dict[str, Any]], None] | None,
) -> Callable[[str, dict[str, Any]], None] | None:
    if callback is None:
        return None

    active_tool_calls: dict[str, dict[str, Any]] = {}

    def wrapped(event: str, data: dict[str, Any]) -> None:
        if event == "tool_call_started":
            call_id = data.get("id")
            if isinstance(call_id, str):
                active_tool_calls[call_id] = dict(data)

        callback(event, data)

        if event == "tool_call_finished" and data.get("ok") is True:
            call_id = data.get("id")
            started = active_tool_calls.pop(call_id, {}) if isinstance(call_id, str) else {}
            paths = _workspace_change_paths(started)
            if paths is not None:
                callback(
                    "workspace_changed",
                    {
                        "session_id": session_id,
                        "paths": paths,
                    },
                )

    return wrapped


def _invoke_chatbot_method(
    method: Callable[..., Any],
    *args: object,
    history: list[Message],
    on_delta: Callable[[str], None] | None = None,
    model_override: str | None = None,
    temperature_override: float | None = None,
    max_tokens_override: int | None = None,
    max_iterations_override: int | None = None,
    system_prompt_override: str | None = None,
    disabled_tools: list[str] | None = None,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"history": history}
    signature = inspect.signature(method)
    if on_delta is not None and "on_delta" in signature.parameters:
        kwargs["on_delta"] = on_delta
    if model_override is not None and "model_override" in signature.parameters:
        kwargs["model_override"] = model_override
    if temperature_override is not None and "temperature_override" in signature.parameters:
        kwargs["temperature_override"] = temperature_override
    if max_tokens_override is not None and "max_tokens_override" in signature.parameters:
        kwargs["max_tokens_override"] = max_tokens_override
    if max_iterations_override is not None and "max_iterations_override" in signature.parameters:
        kwargs["max_iterations_override"] = max_iterations_override
    if system_prompt_override is not None and "system_prompt_override" in signature.parameters:
        kwargs["system_prompt_override"] = system_prompt_override
    if disabled_tools is not None and "disabled_tools" in signature.parameters:
        kwargs["disabled_tools"] = disabled_tools
    if on_event is not None and "on_event" in signature.parameters:
        kwargs["on_event"] = on_event
    return method(*args, **kwargs)


def _build_run_started_payload(
    session_id: str,
    content: MessageContent,
) -> dict[str, Any]:
    preview = _content_to_preview_text(content)
    if isinstance(content, str):
        return {"session_id": session_id, "message": preview}
    return {
        "session_id": session_id,
        "message": preview,
        "content": content,
    }


def _content_to_preview_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
                continue
        elif block_type == "image":
            parts.append("[image]")
            continue
        parts.append(str(block))
    return "\n".join(parts)


def _derive_session_title(first_user_message: str, *, session_id: str) -> str:
    normalized = " ".join(first_user_message.split()).strip()
    if not normalized:
        return "New Chat"
    return normalized[:30]


def _preview_text(text: str, *, limit: int = 80) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _prepare_history_for_persistence(history: list[Message]) -> list[Message]:
    prepared: list[Message] = []
    for raw_message in history:
        message = dict(raw_message)
        message.setdefault("id", _generate_message_id())
        message.setdefault("created_at", _utc_timestamp())
        prepared.append(message)
    return prepared


def _generate_session_id() -> str:
    return f"session_{uuid.uuid4().hex}"


def _generate_message_id() -> str:
    return f"msg_{uuid.uuid4().hex}"


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _stamp_run_id(
    messages: list[Message],
    start_index: int,
    run_id: str,
) -> list[Message]:
    """Tag the assistant messages produced in the current run with ``run_id``.

    Each agent turn (one LLM round-trip) is persisted as its own assistant
    message. Tagging every assistant message of a run with a shared id lets the
    frontend regroup them into a single bubble on reload, mirroring how the
    streaming UI shows one bubble per run. ``start_index`` is the length of the
    history that went *into* the run, so everything at or beyond it is new.
    Messages from earlier runs (and any that already carry a ``run_id``) are
    left untouched.
    """
    if start_index < 0:
        start_index = 0
    stamped: list[Message] = list(messages)
    for index in range(start_index, len(stamped)):
        message = stamped[index]
        if message.get("role") != "assistant":
            continue
        metadata = dict(message.get("metadata") or {})
        if metadata.get("run_id"):
            continue
        metadata["run_id"] = run_id
        message = dict(message)
        message["metadata"] = metadata
        stamped[index] = message
    return stamped


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_session_title(title: str | None) -> str:
    normalized = " ".join((title or "").split()).strip()
    return normalized or "New Chat"


def _normalize_agent_type(agent_type: str | None) -> str | None:
    if not isinstance(agent_type, str):
        return None
    stripped = agent_type.strip()
    return stripped or None


def _workspace_change_paths(event: dict[str, Any]) -> list[str] | None:
    name = event.get("name")
    arguments = event.get("arguments")
    if not isinstance(name, str):
        return None
    if name in {"exec", "apply_patch"}:
        return []
    if name not in {"write_file", "edit_file"}:
        return None
    if not isinstance(arguments, dict):
        return []
    path = arguments.get("path")
    if isinstance(path, str) and path.strip():
        return [path]
    return []


def _mtime_to_utc(path: Path) -> str:
    return datetime.fromtimestamp(
        path.stat().st_mtime,
        tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")


def _validate_upload_filename(name: str) -> None:
    normalized = name.strip()
    if not normalized:
        raise WorkspaceFilenameInvalidError("filename must not be empty")
    if len(normalized) > 255:
        raise WorkspaceFilenameInvalidError("filename must be <= 255 characters")
    if normalized in {".", ".."}:
        raise WorkspaceFilenameInvalidError("filename must not be '.' or '..'")
    if any(char in normalized for char in ("/", "\\", "\x00")):
        raise WorkspaceFilenameInvalidError(
            "filename must not contain '/', '\\', or null bytes",
        )


def _resolve_skills_dir(
    config: Any,
    *,
    config_file: Path | None,
) -> Path | None:
    if config is None or not config.skills_dir:
        return None
    candidate = Path(config.skills_dir).expanduser()
    if not candidate.is_absolute() and config_file is not None:
        candidate = config_file.parent / candidate
    return candidate.resolve()


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
