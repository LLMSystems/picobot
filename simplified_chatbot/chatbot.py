"""High-level facade for the simplified chatbot."""

from __future__ import annotations

from collections.abc import Callable
import inspect
from pathlib import Path
from typing import Any

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.agent.subagent import SubagentManager
from simplified_chatbot.agent.types import Message, MessageContent, RunResult
from simplified_chatbot.config.loader import load_config, resolve_config_path
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.prompts.loader import (
    load_subagent_system_prompt,
    load_system_prompt,
)
from simplified_chatbot.providers.base import ChatProvider
from simplified_chatbot.providers.factory import build_provider
from simplified_chatbot.tools.filesystem import build_default_tool_registry
from simplified_chatbot.tools.registry import ToolRegistry


class SimplifiedChatbot:
    """Minimal configurable chatbot facade."""

    def __init__(
        self,
        config: ChatbotConfig,
        provider: ChatProvider,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        *,
        tool_factory: Callable[..., ToolRegistry] | None = None,
        default_workspace: Path | None = None,
        system_prompt_factory: Callable[[Path | None], str] | None = None,
        subagent_manager: SubagentManager | None = None,
        default_session_id: str | None = None,
    ) -> None:
        self.config = config
        self.provider = provider
        self.system_prompt = system_prompt
        self._tool_factory = tool_factory
        self._system_prompt_factory = system_prompt_factory
        self.subagent_manager = subagent_manager
        self._default_session_id = default_session_id
        self._default_workspace = (
            default_workspace.expanduser().resolve()
            if default_workspace is not None
            else None
        )
        self.tools = tools or build_default_tool_registry(
            workspace=self._default_workspace,
            subagent_manager=subagent_manager,
            session_id=default_session_id,
        )
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
        subagent_manager = None
        tool_factory = None
        if tools is None:
            subagent_system_prompt_factory = lambda workspace: load_subagent_system_prompt(
                config,
                config_path=resolved_path,
                workspace=workspace or default_workspace,
            )

            def build_subagent_chatbot(
                workspace: Path | None,
                model_override: str | None,
            ) -> "SimplifiedChatbot":
                resolved_workspace = (
                    workspace.expanduser().resolve()
                    if workspace is not None
                    else default_workspace
                )
                return cls(
                    config=config,
                    provider=provider,
                    system_prompt=subagent_system_prompt_factory(resolved_workspace),
                    tools=build_default_tool_registry(
                        workspace=resolved_workspace,
                        skills_dir=resolved_skills_dir,
                        profile="subagent",
                    ),
                    tool_factory=lambda next_workspace, _session_id=None: build_default_tool_registry(
                        workspace=next_workspace,
                        skills_dir=resolved_skills_dir,
                        profile="subagent",
                    ),
                    default_workspace=resolved_workspace,
                    system_prompt_factory=subagent_system_prompt_factory,
                    subagent_manager=None,
                )

            subagent_manager = SubagentManager(build_subagent_chatbot)
            resolved_tools = build_default_tool_registry(
                workspace=default_workspace,
                skills_dir=resolved_skills_dir,
                profile="main",
                subagent_manager=subagent_manager,
            )
            tool_factory = lambda workspace, session_id=None: build_default_tool_registry(
                workspace=workspace,
                skills_dir=resolved_skills_dir,
                profile="main",
                subagent_manager=subagent_manager,
                session_id=session_id,
            )
        else:
            resolved_tools = tools
        return cls(
            config=config,
            provider=provider,
            system_prompt=system_prompt,
            tools=resolved_tools,
            tool_factory=tool_factory,
            default_workspace=default_workspace,
            system_prompt_factory=system_prompt_factory,
            subagent_manager=subagent_manager,
        )

    @property
    def supports_workspace_clone(self) -> bool:
        """Whether this chatbot can derive a fresh tool registry for another workspace."""
        return self._tool_factory is not None

    def for_workspace(
        self,
        workspace: str | Path,
        *,
        session_id: str | None = None,
    ) -> "SimplifiedChatbot":
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
            tools=_invoke_tool_factory(self._tool_factory, resolved_workspace, session_id),
            tool_factory=self._tool_factory,
            default_workspace=resolved_workspace,
            system_prompt_factory=self._system_prompt_factory,
            subagent_manager=self.subagent_manager,
            default_session_id=session_id,
        )

    def build_messages(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
    ) -> list[Message]:
        """Build request messages without calling the provider."""
        return self._loop.build_messages(message, history=history)

    def run(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one model turn."""
        return self._loop.run(
            message,
            history=history,
            model_override=model_override,
            on_event=on_event,
        )

    async def run_async(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        model_override: str | None = None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one model turn asynchronously."""
        return await self._loop.run_async(
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

    async def continue_async(
        self,
        history: list[Message],
        *,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Continue from existing history without appending a new user message."""
        return await self._loop.continue_async(
            history,
            model_override=model_override,
            on_event=on_event,
        )

    def run_stream(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> RunResult:
        """Run one streamed model turn."""
        return self._loop.run_stream(
            message,
            history=history,
            on_delta=on_delta,
            model_override=model_override,
            on_event=on_event,
        )

    async def run_stream_async(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
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
        """Run one streamed model turn asynchronously."""
        return await self._loop.run_stream_async(
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


def _invoke_tool_factory(
    factory: Callable[..., ToolRegistry],
    workspace: Path,
    session_id: str | None,
) -> ToolRegistry:
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):
        return factory(workspace)
    if len(signature.parameters) >= 2:
        return factory(workspace, session_id)
    return factory(workspace)
