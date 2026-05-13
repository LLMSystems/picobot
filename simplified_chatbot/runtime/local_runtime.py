"""Local multi-turn runtime built on top of SimplifiedChatbot."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplified_chatbot.agent.types import Message
from simplified_chatbot.agent.types import RunResult
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
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_message_async(...) instead of handle_message(...).",
            )
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = chatbot.run(message, history=history)
        self.store.save_history(session_id, result.messages)
        return result

    def handle_message_stream(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> RunResult:
        if isinstance(self.store, AsyncSessionStore):
            raise RuntimeError(
                "This runtime is using an AsyncSessionStore. "
                "Use handle_message_stream_async(...) instead of handle_message_stream(...).",
            )
        chatbot = self._get_chatbot_for_session(session_id)
        history = self.store.load_history(session_id)
        result = chatbot.run_stream(message, history=history, on_delta=on_delta)
        self.store.save_history(session_id, result.messages)
        return result

    async def handle_message_async(self, session_id: str, message: str) -> RunResult:
        history = await self._load_history_async(session_id)
        result = await self._run_chat_async(session_id, message, history=history)
        await self._save_history_async(session_id, result.messages)
        return result

    async def handle_message_stream_async(
        self,
        session_id: str,
        message: str,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> RunResult:
        history = await self._load_history_async(session_id)
        result = await self._run_chat_stream_async(
            session_id,
            message,
            history=history,
            on_delta=on_delta,
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

    async def load_history_async(self, session_id: str) -> list[Message]:
        return await self._load_history_async(session_id)

    async def _load_history_async(self, session_id: str) -> list[Message]:
        if isinstance(self.store, AsyncSessionStore):
            return await self.store.load_history(session_id)
        return await asyncio.to_thread(self.store.load_history, session_id)

    async def _save_history_async(self, session_id: str, history: list[Message]) -> None:
        if isinstance(self.store, AsyncSessionStore):
            await self.store.save_history(session_id, history)
            return
        await asyncio.to_thread(self.store.save_history, session_id, history)

    async def _run_chat_async(
        self,
        session_id: str,
        message: str,
        history: list[Message],
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_async = getattr(chatbot, "run_async", None)
        if callable(run_async):
            return await run_async(message, history=history)
        return await asyncio.to_thread(chatbot.run, message, history=history)

    async def _run_chat_stream_async(
        self,
        session_id: str,
        message: str,
        *,
        history: list[Message],
        on_delta: Callable[[str], None] | None,
    ) -> RunResult:
        chatbot = self._get_chatbot_for_session(session_id)
        run_stream_async = getattr(chatbot, "run_stream_async", None)
        if callable(run_stream_async):
            return await run_stream_async(
                message,
                history=history,
                on_delta=on_delta,
            )
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
