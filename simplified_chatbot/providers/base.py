"""Base provider abstraction for the simplified chatbot."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any

from simplified_chatbot.agent.types import Message


@dataclass(slots=True)
class ToolCallRequest:
    """Normalized tool call request from an LLM."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai_tool_call(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }


@dataclass(slots=True)
class ProviderResponse:
    """Normalized provider response."""

    content: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any | None = None

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def should_execute_tools(self) -> bool:
        if not self.has_tool_calls:
            return False
        return self.finish_reason in {"tool_calls", "stop"}


class ChatProvider(ABC):
    """Async-first provider interface with sync compatibility wrappers."""

    def generate(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Sync wrapper for generate_async()."""
        return self._run_sync(
            lambda: self.generate_async(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                tools=tools,
            ),
            method_name="generate",
            async_method_name="generate_async",
        )

    def stream_generate(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        on_delta: Callable[[str], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Sync wrapper for stream_generate_async()."""
        return self._run_sync(
            lambda: self.stream_generate_async(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                on_delta=on_delta,
                tools=tools,
            ),
            method_name="stream_generate",
            async_method_name="stream_generate_async",
        )

    @abstractmethod
    async def generate_async(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Generate one assistant response from a message list."""

    @abstractmethod
    async def stream_generate_async(
        self,
        messages: list[Message],
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        on_delta: Callable[[str], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> ProviderResponse:
        """Stream one assistant response and return the aggregated result."""

    @staticmethod
    def _run_sync(
        coroutine_factory: Callable[[], Any],
        *,
        method_name: str,
        async_method_name: str,
    ) -> ProviderResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine_factory())
        raise RuntimeError(
            f"{method_name}(...) cannot be called inside an active event loop. "
            f"Use await {async_method_name}(...) instead.",
        )
