"""Local multi-turn runtime built on top of SimplifiedChatbot."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import inspect
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import uuid

from simplified_chatbot.agent.types import Message, MessageContent, RunResult
from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.loader import load_config
from simplified_chatbot.runtime.session_store import (
    AsyncSessionStore,
    InMemorySessionStore,
    JsonlSessionStore,
    SessionStore,
)
from simplified_chatbot.runtime.session_workspace import SessionWorkspaceManager
from simplified_chatbot.tools.shell import ExecTool

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
        max_upload_file_bytes: int = _DEFAULT_MAX_UPLOAD_FILE_BYTES,
        max_upload_files_per_request: int = _DEFAULT_MAX_UPLOAD_FILES_PER_REQUEST,
        chrome_debugging_port: int | None = None,
    ) -> None:
        self.chatbot = chatbot
        self.store = store or InMemorySessionStore()
        self.workspace_manager = (
            SessionWorkspaceManager(workspace_root_dir)
            if workspace_root_dir is not None
            else None
        )
        self._session_chatbots: dict[str, Any] = {}
        self.max_upload_file_bytes = max_upload_file_bytes
        self.max_upload_files_per_request = max_upload_files_per_request
        self.chrome_debugging_port = chrome_debugging_port
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
        browser_config = getattr(loaded_config, "browser", None) if loaded_config is not None else None
        chrome_port = (
            browser_config.get("chromeDebuggingPort")
            if isinstance(browser_config, dict)
            else None
        )
        return cls(
            chatbot=bot,
            store=store,
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
        )

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
            _prepare_history_for_persistence(result.messages),
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
            _prepare_history_for_persistence(result.messages),
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
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            _build_run_started_payload(session_id, content),
        )
        resolved_model = self._resolve_model_override(model_override)
        history = await self._load_history_async(session_id)
        result = await self._run_chat_async(
            session_id,
            content,
            history=history,
            model_override=resolved_model,
            temperature_override=temperature_override,
            max_tokens_override=max_tokens_override,
            max_iterations_override=max_iterations_override,
            system_prompt_override=system_prompt_override,
            disabled_tools=disabled_tools,
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
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        event_callback = _build_runtime_event_callback(session_id, on_event)
        _emit_runtime_event(
            event_callback,
            "run_started",
            _build_run_started_payload(session_id, content),
        )
        resolved_model = self._resolve_model_override(model_override)
        history = await self._load_history_async(session_id)
        result = await self._run_chat_stream_async(
            session_id,
            content,
            history=history,
            on_delta=on_delta,
            model_override=resolved_model,
            temperature_override=temperature_override,
            max_tokens_override=max_tokens_override,
            max_iterations_override=max_iterations_override,
            system_prompt_override=system_prompt_override,
            disabled_tools=disabled_tools,
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
        self._bind_chrome_port(session_chatbot)
        self._session_chatbots[session_id] = session_chatbot
        return session_chatbot

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
