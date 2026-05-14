"""High-level facade for the simplified chatbot."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.agent.types import Message, RunResult
from simplified_chatbot.config.loader import load_config, resolve_config_path
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.prompts.loader import load_system_prompt
from simplified_chatbot.providers.base import ChatProvider
from simplified_chatbot.providers.factory import build_provider
from simplified_chatbot.tools.registry import ToolRegistry
from simplified_chatbot.tools.filesystem import build_default_tool_registry


class SimplifiedChatbot:
    """Minimal configurable chatbot facade."""

    def __init__(
        self,
        config: ChatbotConfig,
        provider: ChatProvider,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        *,
        tool_factory: Callable[[Path], ToolRegistry] | None = None,
        default_workspace: Path | None = None,
        system_prompt_factory: Callable[[Path | None], str] | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.system_prompt = system_prompt
        self._tool_factory = tool_factory
        self._system_prompt_factory = system_prompt_factory
        self._default_workspace = (
            default_workspace.expanduser().resolve()
            if default_workspace is not None
            else None
        )
        self.tools = tools or build_default_tool_registry(workspace=self._default_workspace)
        self._loop = AgentLoop(
            provider=provider,
            config=config,
            system_prompt=system_prompt,
            tools=self.tools,
        )

    @classmethod
    def from_config(
        cls,
        config_path: str | Path | None = None,
        *,
        tools: ToolRegistry | None = None,
    ) -> "SimplifiedChatbot":
        """Build a chatbot instance from a config file."""
        resolved_path = resolve_config_path(config_path)
        config = load_config(resolved_path)
        provider = build_provider(config)
        default_workspace = resolved_path.parent
        resolved_skills_dir = _resolve_skills_dir(config, resolved_path=resolved_path)
        system_prompt_factory = lambda workspace: load_system_prompt(
            config,
            config_path=resolved_path,
            workspace=workspace or default_workspace,
        )
        system_prompt = system_prompt_factory(default_workspace)
        resolved_tools = tools or build_default_tool_registry(
            workspace=default_workspace,
            skills_dir=resolved_skills_dir,
        )
        tool_factory = (
            None
            if tools is not None
            else lambda workspace: build_default_tool_registry(
                workspace=workspace,
                skills_dir=resolved_skills_dir,
            )
        )
        return cls(
            config=config,
            provider=provider,
            system_prompt=system_prompt,
            tools=resolved_tools,
            tool_factory=tool_factory,
            default_workspace=default_workspace,
            system_prompt_factory=system_prompt_factory,
        )

    @property
    def supports_workspace_clone(self) -> bool:
        """Whether this chatbot can derive a fresh tool registry for another workspace."""
        return self._tool_factory is not None

    def for_workspace(self, workspace: str | Path) -> "SimplifiedChatbot":
        """Create a new chatbot instance bound to a specific workspace."""
        if self._tool_factory is None:
            raise ValueError("This chatbot does not support workspace cloning")
        resolved_workspace = Path(workspace).expanduser().resolve()
        return SimplifiedChatbot(
            config=self.config,
            provider=self.provider,
            system_prompt=(
                self._system_prompt_factory(resolved_workspace)
                if self._system_prompt_factory is not None
                else self.system_prompt
            ),
            tools=self._tool_factory(resolved_workspace),
            tool_factory=self._tool_factory,
            default_workspace=resolved_workspace,
            system_prompt_factory=self._system_prompt_factory,
        )

    def build_messages(
        self,
        message: str,
        history: list[Message] | None = None,
    ) -> list[Message]:
        """Build request messages without calling the provider."""
        return self._loop.build_messages(message, history=history)

    def run(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one model turn."""
        return self._loop.run(message, history=history, on_event=on_event)

    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one model turn asynchronously."""
        return await self._loop.run_async(
            message,
            history=history,
            on_event=on_event,
        )

    def run_stream(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one streamed model turn."""
        return self._loop.run_stream(
            message,
            history=history,
            on_delta=on_delta,
            on_event=on_event,
        )

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one streamed model turn asynchronously."""
        return await self._loop.run_stream_async(
            message,
            history=history,
            on_delta=on_delta,
            on_event=on_event,
        )


def _resolve_skills_dir(
    config: ChatbotConfig,
    *,
    resolved_path: Path,
) -> Path | None:
    if not config.skills_dir:
        return None
    candidate = Path(config.skills_dir).expanduser()
    if not candidate.is_absolute():
        candidate = resolved_path.parent / candidate
    return candidate.resolve()
