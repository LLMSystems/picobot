"""Local multi-turn runtime built on top of SimplifiedChatbot."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone
import inspect
from pathlib import Path
from typing import Any
import uuid

from simplified_chatbot.agent.types import Message, RunResult
from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.loader import load_config
from simplified_chatbot.runtime.session_store import (
    AsyncSessionStore,
    InMemorySessionStore,
    JsonlSessionStore,
    SessionStore,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager


class LocalAgentRuntime:
    """Session-aware runtime that persists conversation history by session_id."""

    _DEFAULT_WORKSPACE_TREE_MAX = 200
    _DEFAULT_WORKSPACE_FILE_LIMIT = 2000

    def __init__(
        self,
        chatbot: SimplifiedChatbot,
        store: SessionStore | AsyncSessionStore | None = None,
        workspace_root_dir: str | Path | None = None,
    ) -> None:
        self.chatbot = chatbot
        self.store = store or InMemorySessionStore()
        self.workspace_manager = (
            SessionWorkspaceManager(workspace_root_dir)
            if workspace_root_dir is not None
            else None
        )
        self._session_chatbots: dict[str, Any] = {}

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
        bot = SimplifiedChatbot.from_config(config_file)
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
        return cls(
            chatbot=bot,
            store=store,
            workspace_root_dir=resolved_workspace_root,
        )

    def handle_message(self, session_id: str, message: str) -> RunResult:
        return self.handle_message_with_events(
            session_id,
            message,
            on_event=None,
        )

    def handle_message_with_events(
        self,
        session_id: str,
        message: str,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_message_async(...) instead of handle_message(...).",
            )
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            {"session_id": session_id, "message": message},
        )
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = _invoke_chatbot_method(
            chatbot.run,
            message,
            history=history,
            on_event=event_callback,
        )
        self.store.save_history(
            session_id,
            _prepare_history_for_persistence(result.messages),
        )
        return result

    def handle_message_stream(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_message_stream_async(...) instead of handle_message_stream(...).",
            )
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            {"session_id": session_id, "message": message},
        )
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = _invoke_chatbot_method(
            chatbot.run_stream,
            message,
            history=history,
            on_delta=on_delta,
            on_event=event_callback,
        )
        self.store.save_history(
            session_id,
            _prepare_history_for_persistence(result.messages),
        )
        return result

    async def handle_message_async(
        self,
        session_id: str,
        message: str,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            {"session_id": session_id, "message": message},
        )
        history = await self._load_history_async(session_id)
        result = await self._run_chat_async(
            session_id,
            message,
            history=history,
            on_event=event_callback,
        )
        await self._save_history_async(session_id, result.messages)
        return result

    async def handle_message_stream_async(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            {"session_id": session_id, "message": message},
        )
        history = await self._load_history_async(session_id)
        result = await self._run_chat_stream_async(
            session_id,
            message,
            history=history,
            on_delta=on_delta,
            on_event=event_callback,
        )
        await self._save_history_async(session_id, result.messages)
        return result

    def reset_session(self, session_id: str) -> None:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use reset_session_async(...) instead of reset_session(...).",
            )
        self.store.delete_session(session_id)
        self._session_chatbots.pop(session_id, None)

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
    ) -> dict[str, object]:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use create_session_async(...) instead of create_session(...).",
            )
        resolved_session_id = session_id or _generate_session_id()
        metadata = self.store.create_session(
            resolved_session_id,
            {"title": _normalize_session_title(title)},
        )
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
        if isinstance(self.store, AsyncSessionStore):
            await self.store.delete_session(session_id)
        else:
            await asyncio.to_thread(self.store.delete_session, session_id)
        self._session_chatbots.pop(session_id, None)

    async def list_sessions_async(self) -> list[str]:
        if isinstance(self.store, AsyncSessionStore):
            return await self.store.list_sessions()
        return await asyncio.to_thread(self.store.list_sessions)

    async def list_session_summaries_async(self) -> list[dict[str, object]]:
        session_ids = await self.list_sessions_async()
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

    async def create_session_async(
        self,
        *,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        resolved_session_id = session_id or _generate_session_id()
        payload = {"title": _normalize_session_title(title)}
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
            self.workspace_manager.ensure_workspace(resolved_session_id)
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

    async def _run_chat_async(
        self,
        session_id: str,
        message: str,
        history: list[Message],
        on_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_async = getattr(chatbot, "run_async", None)
        if callable(run_async):
            result = _invoke_chatbot_method(
                run_async,
                message,
                history=history,
                on_event=on_event,
            )
            if inspect.isawaitable(result):
                return await result
            return result
        return await asyncio.to_thread(chatbot.run, message, history=history)

    async def _run_chat_stream_async(
        self,
        session_id: str,
        message: str,
        *,
        history: list[Message],
        on_delta: Callable[[str], None] | None,
        on_event: Callable[[str, dict[str, Any]], None] | None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_stream_async = getattr(chatbot, "run_stream_async", None)
        if callable(run_stream_async):
            result = _invoke_chatbot_method(
                run_stream_async,
                message,
                history=history,
                on_delta=on_delta,
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
        )

    def _get_chatbot_for_session(self, session_id: str) -> Any:
        if self.workspace_manager is None:
            return self.chatbot
        if not isinstance(self.chatbot, SimplifiedChatbot):
            return self.chatbot
        if not self.chatbot.supports_workspace_clone:
            return self.chatbot

        cached = self._session_chatbots.get(session_id)
        if cached is not None:
            return cached

        workspace = self.workspace_manager.ensure_workspace(session_id)
        session_chatbot = self.chatbot.for_workspace(workspace)
        self._session_chatbots[session_id] = session_chatbot
        return session_chatbot

    @staticmethod
    def _build_session_summary(
        session_id: str,
        history: list[Message],
        metadata: dict[str, object] | None,
    ) -> dict[str, object]:
        first_user = next(
            (
                str(message["content"])
                for message in history
                if message.get("role") == "user" and str(message.get("content", "")).strip()
            ),
            "",
        )
        last_user = next(
            (
                str(message["content"])
                for message in reversed(history)
                if message.get("role") == "user" and str(message.get("content", "")).strip()
            ),
            "",
        )
        last_assistant = next(
            (
                str(message["content"])
                for message in reversed(history)
                if message.get("role") == "assistant" and str(message.get("content", "")).strip()
            ),
            "",
        )
        session_metadata = metadata or {}
        created_at = session_metadata.get("created_at")
        updated_at = session_metadata.get("updated_at")
        title = session_metadata.get("title")
        return {
            "session_id": session_id,
            "title": (
                str(title)
                if isinstance(title, str) and title.strip()
                else _derive_session_title(first_user, session_id=session_id)
            ),
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
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {"history": history}
    signature = inspect.signature(method)
    if on_delta is not None and "on_delta" in signature.parameters:
        kwargs["on_delta"] = on_delta
    if on_event is not None and "on_event" in signature.parameters:
        kwargs["on_event"] = on_event
    return method(*args, **kwargs)


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


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_session_title(title: str | None) -> str:
    normalized = " ".join((title or "").split()).strip()
    return normalized or "New Chat"


def _workspace_change_paths(started_event: dict[str, Any]) -> list[str] | None:
    name = started_event.get("name")
    arguments = started_event.get("arguments")
    if not isinstance(name, str):
        return None
    if name == "exec":
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
