"""Minimal single-iteration agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
import json

from simplified_chatbot.agent.types import Message, RunResult
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ChatProvider
from simplified_chatbot.tools.registry import ToolRegistry

_TRIM_SAFETY_BUFFER_TOKENS = 1024


class AgentLoop:
    """Build messages, execute tool-enabled model turns, and return history."""

    def __init__(
        self,
        provider: ChatProvider,
        config: ChatbotConfig,
        system_prompt: str,
        tools: ToolRegistry | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._system_prompt = system_prompt
        self._tools = tools or ToolRegistry()

    @property
    def system_prompt(self) -> str:
        """Return the current system prompt."""
        return self._system_prompt

    def build_messages(
        self,
        message: str,
        history: list[Message] | None = None,
    ) -> list[Message]:
        """Build the provider request messages for a single user turn."""
        text = self._normalize_user_message(message)
        normalized_history = self._normalize_history(history)
        return [
            {"role": "system", "content": self._system_prompt},
            *normalized_history,
            {"role": "user", "content": text},
        ]

    def run(
        self,
        message: str,
        history: list[Message] | None = None,
    ) -> RunResult:
        """Sync wrapper for run_async()."""
        return self._run_sync(
            lambda: self.run_async(message, history=history),
            method_name="run",
            async_method_name="run_async",
        )

    def run_stream(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Sync wrapper for run_stream_async()."""
        return self._run_sync(
            lambda: self.run_stream_async(
                message,
                history=history,
                on_delta=on_delta,
            ),
            method_name="run_stream",
            async_method_name="run_stream_async",
        )

    async def run_async(
        self,
        message: str,
        history: list[Message] | None = None,
    ) -> RunResult:
        """Execute one user turn and return the updated conversation history."""
        return await self._run_internal_async(
            message,
            history=history,
            stream=False,
            on_delta=None,
        )

    async def run_stream_async(
        self,
        message: str,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
    ) -> RunResult:
        """Execute one streamed user turn and return the aggregated result."""
        return await self._run_internal_async(
            message,
            history=history,
            stream=True,
            on_delta=on_delta,
        )

    async def _run_internal_async(
        self,
        message: str,
        *,
        history: list[Message] | None,
        stream: bool,
        on_delta: Callable[[str], None] | None,
    ) -> RunResult:
        text = self._normalize_user_message(message)
        conversation = [
            *self._normalize_history(history),
            {"role": "user", "content": text},
        ]
        tools_used: list[str] = []
        tool_definitions = self._tools.get_definitions() or None
        usage: dict[str, int] = {}

        for _ in range(self._config.max_iterations):
            trimmed_conversation = self._trim_conversation(conversation)
            request_messages = [
                {"role": "system", "content": self._system_prompt},
                *trimmed_conversation,
            ]
            response = await self._call_provider_async(
                request_messages,
                stream=stream,
                on_delta=on_delta,
                tools=tool_definitions,
            )
            usage = response.usage or usage

            if response.should_execute_tools:
                conversation.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            tool_call.to_openai_tool_call()
                            for tool_call in response.tool_calls
                        ],
                    },
                )
                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)
                    result = await self._execute_tool_async(
                        tool_call.name,
                        tool_call.arguments,
                    )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": self._normalize_tool_result(result),
                        },
                    )
                continue

            conversation.append(
                {
                    "role": "assistant",
                    "content": response.content,
                },
            )
            return RunResult(
                content=response.content,
                messages=conversation,
                model=self._config.model,
                provider=self._config.provider,
                usage=response.usage,
                tools_used=tools_used,
                stop_reason=response.finish_reason,
            )

        final_message = "Stopped after reaching max_iterations during tool calling."
        conversation.append({"role": "assistant", "content": final_message})
        return RunResult(
            content=final_message,
            messages=conversation,
            model=self._config.model,
            provider=self._config.provider,
            usage=usage,
            tools_used=tools_used,
            stop_reason="max_iterations",
        )

    async def _execute_tool_async(
        self,
        name: str,
        arguments: dict[str, object],
    ) -> object:
        execute_async = getattr(self._tools, "execute_async", None)
        if callable(execute_async):
            result = execute_async(name, arguments)
            if inspect.isawaitable(result):
                return await result
            return result

        result = self._tools.execute(name, arguments)
        if inspect.isawaitable(result):
            return await result
        return result

    def _trim_conversation(self, conversation: list[Message]) -> list[Message]:
        """Trim oldest turns when the estimated prompt budget is exceeded."""
        budget = max(
            self._config.context_window_tokens
            - self._config.max_tokens
            - _TRIM_SAFETY_BUFFER_TOKENS,
            1,
        )
        estimated = self._estimate_prompt_tokens(self._system_prompt, conversation)
        if estimated <= budget:
            return list(conversation)

        turns = self._group_conversation_turns(conversation)
        while len(turns) > 1 and estimated > budget:
            turns.pop(0)
            flattened = self._flatten_turns(turns)
            estimated = self._estimate_prompt_tokens(self._system_prompt, flattened)

        return self._flatten_turns(turns)

    async def _call_provider_async(
        self,
        messages: list[Message],
        *,
        stream: bool,
        on_delta: Callable[[str], None] | None,
        tools: list[dict[str, object]] | None,
    ):
        if stream:
            stream_generate_async = getattr(self._provider, "stream_generate_async", None)
            if callable(stream_generate_async):
                response = stream_generate_async(
                    messages,
                    model=self._config.model,
                    max_tokens=self._config.max_tokens,
                    temperature=self._config.temperature,
                    timeout=self._config.request_timeout,
                    on_delta=on_delta,
                    tools=tools,
                )
                if inspect.isawaitable(response):
                    return await response
                return response
            return await asyncio.to_thread(
                self._provider.stream_generate,
                messages,
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                timeout=self._config.request_timeout,
                on_delta=on_delta,
                tools=tools,
            )

        generate_async = getattr(self._provider, "generate_async", None)
        if callable(generate_async):
            response = generate_async(
                messages,
                model=self._config.model,
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
                timeout=self._config.request_timeout,
                tools=tools,
            )
            if inspect.isawaitable(response):
                return await response
            return response
        return await asyncio.to_thread(
            self._provider.generate,
            messages,
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            timeout=self._config.request_timeout,
            tools=tools,
        )

    @staticmethod
    def _run_sync(
        coroutine_factory: Callable[[], object],
        *,
        method_name: str,
        async_method_name: str,
    ) -> RunResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(coroutine_factory())
            if isinstance(result, RunResult):
                return result
            raise TypeError(f"{async_method_name}(...) must return RunResult")
        raise RuntimeError(
            f"{method_name}(...) cannot be called inside an active event loop. "
            f"Use await {async_method_name}(...) instead.",
        )

    @staticmethod
    def _normalize_tool_result(result: object) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)

    @staticmethod
    def _group_conversation_turns(conversation: list[Message]) -> list[list[Message]]:
        """Group messages into turns so trimming removes complete tool chains."""
        turns: list[list[Message]] = []
        current: list[Message] = []
        for message in conversation:
            if message["role"] == "user" and current:
                turns.append(current)
                current = [message]
            else:
                current.append(message)
        if current:
            turns.append(current)
        return turns or [[]]

    @staticmethod
    def _flatten_turns(turns: list[list[Message]]) -> list[Message]:
        flattened: list[Message] = []
        for turn in turns:
            flattened.extend(turn)
        return flattened

    @staticmethod
    def _estimate_prompt_tokens(system_prompt: str, conversation: list[Message]) -> int:
        """Estimate prompt size with a lightweight chars-to-tokens heuristic."""
        parts = [system_prompt]
        for message in conversation:
            parts.append(message.get("content", ""))
            if isinstance(message.get("tool_calls"), list):
                parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))
            tool_call_id = message.get("tool_call_id")
            if isinstance(tool_call_id, str):
                parts.append(tool_call_id)
            name = message.get("name")
            if isinstance(name, str):
                parts.append(name)
        text = "\n".join(parts)
        return max(1, len(text) // 4)

    @staticmethod
    def _normalize_user_message(message: str) -> str:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not message.strip():
            raise ValueError("message must not be empty")
        return message

    @staticmethod
    def _normalize_history(history: list[Message] | None) -> list[Message]:
        if history is None:
            return []
        if not isinstance(history, list):
            raise TypeError("history must be a list of messages")

        normalized: list[Message] = []
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                raise TypeError(f"history[{index}] must be a message dictionary")

            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant", "tool"}:
                raise ValueError(
                    "history messages may only use 'user', 'assistant', or 'tool' roles",
                )
            if not isinstance(content, str):
                raise TypeError(f"history[{index}].content must be a string")
            message: Message = {"role": role, "content": content}
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                message["tool_calls"] = item["tool_calls"]
            if role == "tool":
                tool_call_id = item.get("tool_call_id")
                name = item.get("name")
                if not isinstance(tool_call_id, str):
                    raise TypeError(f"history[{index}].tool_call_id must be a string")
                if not isinstance(name, str):
                    raise TypeError(f"history[{index}].name must be a string")
                message["tool_call_id"] = tool_call_id
                message["name"] = name
            normalized.append(message)
        return normalized
