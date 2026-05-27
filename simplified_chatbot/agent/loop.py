"""Minimal single-iteration agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import inspect
import json
from typing import Any

from simplified_chatbot.agent.types import ContentBlock, Message, MessageContent, RunResult
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ChatProvider
from simplified_chatbot.tools.registry import ToolRegistry

_TRIM_SAFETY_BUFFER_TOKENS = 1024
EventCallback = Callable[[str, dict[str, Any]], None]


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
        message: MessageContent,
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
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        model_override: str | None = None,
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Sync wrapper for run_async()."""
        return self._run_sync(
            lambda: self.run_async(
                message,
                history=history,
                model_override=model_override,
                on_event=on_event,
            ),
            method_name="run",
            async_method_name="run_async",
        )

    def run_stream(
        self,
        message: MessageContent,
        history: list[Message] | None = None,
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Sync wrapper for run_stream_async()."""
        return self._run_sync(
            lambda: self.run_stream_async(
                message,
                history=history,
                on_delta=on_delta,
                model_override=model_override,
                on_event=on_event,
            ),
            method_name="run_stream",
            async_method_name="run_stream_async",
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
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Execute one user turn and return the updated conversation history."""
        conversation = [
            *self._normalize_history(history),
            {"role": "user", "content": self._normalize_user_message(message)},
        ]
        return await self._run_conversation_async(
            conversation,
            stream=False,
            on_delta=None,
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
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Continue from existing history without appending a new user message."""
        return await self._run_conversation_async(
            self._normalize_history(history),
            stream=False,
            on_delta=None,
            model_override=model_override,
            temperature_override=temperature_override,
            max_tokens_override=max_tokens_override,
            max_iterations_override=max_iterations_override,
            system_prompt_override=system_prompt_override,
            disabled_tools=disabled_tools,
            on_event=on_event,
        )

    async def continue_stream_async(
        self,
        history: list[Message],
        *,
        on_delta: Callable[[str], None] | None = None,
        model_override: str | None = None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Continue from existing history with streamed deltas."""
        return await self._run_conversation_async(
            self._normalize_history(history),
            stream=True,
            on_delta=on_delta,
            model_override=model_override,
            temperature_override=temperature_override,
            max_tokens_override=max_tokens_override,
            max_iterations_override=max_iterations_override,
            system_prompt_override=system_prompt_override,
            disabled_tools=disabled_tools,
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
        on_event: EventCallback | None = None,
    ) -> RunResult:
        """Execute one streamed user turn and return the aggregated result."""
        conversation = [
            *self._normalize_history(history),
            {"role": "user", "content": self._normalize_user_message(message)},
        ]
        return await self._run_conversation_async(
            conversation,
            stream=True,
            on_delta=on_delta,
            model_override=model_override,
            temperature_override=temperature_override,
            max_tokens_override=max_tokens_override,
            max_iterations_override=max_iterations_override,
            system_prompt_override=system_prompt_override,
            disabled_tools=disabled_tools,
            on_event=on_event,
        )

    async def _run_conversation_async(
        self,
        conversation: list[Message],
        *,
        stream: bool,
        on_delta: Callable[[str], None] | None,
        model_override: str | None,
        temperature_override: float | None = None,
        max_tokens_override: int | None = None,
        max_iterations_override: int | None = None,
        system_prompt_override: str | None = None,
        disabled_tools: list[str] | None = None,
        on_event: EventCallback | None,
    ) -> RunResult:
        effective_model = self._resolve_effective_model(model_override)
        effective_temperature = temperature_override if temperature_override is not None else self._config.temperature
        effective_max_tokens = max_tokens_override if max_tokens_override is not None else self._config.max_tokens
        effective_max_iterations = max_iterations_override if max_iterations_override is not None else self._config.max_iterations
        effective_system_prompt = system_prompt_override.strip() if system_prompt_override else self._system_prompt
        disabled_set = set(disabled_tools) if disabled_tools else set()
        all_definitions = self._tools.get_definitions() or []
        filtered_definitions = [
            d for d in all_definitions
            if d.get("function", {}).get("name") not in disabled_set
        ]
        tool_definitions = filtered_definitions or None
        tools_used: list[str] = []
        usage: dict[str, int] = {}

        for _ in range(effective_max_iterations):
            trimmed_conversation = self._trim_conversation(conversation)
            request_messages = [
                {"role": "system", "content": effective_system_prompt},
                *trimmed_conversation,
            ]
            response = await self._call_provider_async(
                request_messages,
                model=effective_model,
                stream=stream,
                on_delta=on_delta,
                tools=tool_definitions,
                temperature=effective_temperature,
                max_tokens=effective_max_tokens,
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
                    self._emit_event(
                        on_event,
                        "tool_call_started",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    )
                    try:
                        result = await self._execute_tool_async(
                            tool_call.name,
                            tool_call.arguments,
                        )
                    except Exception as exc:
                        self._emit_event(
                            on_event,
                            "tool_call_finished",
                            {
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "ok": False,
                                "error": str(exc),
                            },
                        )
                        raise
                    self._emit_event(
                        on_event,
                        "tool_call_finished",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "ok": True,
                            "result": self._serialize_event_result(result),
                        },
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
                model=effective_model,
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
            model=effective_model,
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
        model: str,
        stream: bool,
        on_delta: Callable[[str], None] | None,
        tools: list[dict[str, object]] | None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        effective_temperature = temperature if temperature is not None else self._config.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self._config.max_tokens

        if stream:
            stream_generate_async = getattr(self._provider, "stream_generate_async", None)
            if callable(stream_generate_async):
                response = stream_generate_async(
                    messages,
                    model=model,
                    max_tokens=effective_max_tokens,
                    temperature=effective_temperature,
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
                model=model,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
                timeout=self._config.request_timeout,
                on_delta=on_delta,
                tools=tools,
            )

        generate_async = getattr(self._provider, "generate_async", None)
        if callable(generate_async):
            response = generate_async(
                messages,
                model=model,
                max_tokens=effective_max_tokens,
                temperature=effective_temperature,
                timeout=self._config.request_timeout,
                tools=tools,
            )
            if inspect.isawaitable(response):
                return await response
            return response
        return await asyncio.to_thread(
            self._provider.generate,
            messages,
            model=model,
            max_tokens=effective_max_tokens,
            temperature=effective_temperature,
            timeout=self._config.request_timeout,
            tools=tools,
        )

    def _resolve_effective_model(self, model_override: str | None) -> str:
        if model_override is None:
            return self._config.model
        stripped = model_override.strip()
        if not stripped:
            raise ValueError("model_override must not be empty")
        return stripped

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
    def _serialize_event_result(result: object) -> Any:
        try:
            json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)
        return result

    @staticmethod
    def _emit_event(
        callback: EventCallback | None,
        event: str,
        data: dict[str, Any],
    ) -> None:
        if callback is not None:
            callback(event, data)

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
            parts.append(AgentLoop._stringify_message_content(message.get("content", "")))
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
    def _normalize_user_message(message: MessageContent) -> MessageContent:
        if isinstance(message, str):
            if not message.strip():
                raise ValueError("message must not be empty")
            return message

        if not isinstance(message, list):
            raise TypeError("message must be a string or a list of content blocks")
        return AgentLoop._normalize_multimodal_content(message, field_name="message")

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
            if role not in {"system", "user", "assistant", "tool"}:
                raise ValueError(
                    "history messages may only use 'system', 'user', 'assistant', or 'tool' roles",
                )
            if role == "user":
                if isinstance(content, str):
                    normalized_content: MessageContent = content
                elif isinstance(content, list):
                    normalized_content = AgentLoop._normalize_multimodal_content(
                        content,
                        field_name=f"history[{index}].content",
                    )
                else:
                    raise TypeError(
                        f"history[{index}].content must be a string or content block list",
                    )
            elif role in {"system", "assistant", "tool"}:
                if not isinstance(content, str):
                    raise TypeError(f"history[{index}].content must be a string")
                normalized_content = content
            else:  # pragma: no cover
                raise ValueError(f"Unsupported history role: {role}")
            message: Message = {"role": role, "content": normalized_content}
            metadata = item.get("metadata")
            if metadata is not None:
                if not isinstance(metadata, dict):
                    raise TypeError(f"history[{index}].metadata must be a dictionary")
                message["metadata"] = dict(metadata)
            message_id = item.get("id")
            if message_id is not None:
                if not isinstance(message_id, str):
                    raise TypeError(f"history[{index}].id must be a string")
                message["id"] = message_id
            created_at = item.get("created_at")
            if created_at is not None:
                if not isinstance(created_at, str):
                    raise TypeError(f"history[{index}].created_at must be a string")
                message["created_at"] = created_at
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

    @staticmethod
    def _normalize_multimodal_content(
        content: list[ContentBlock],
        *,
        field_name: str,
    ) -> list[ContentBlock]:
        if not content:
            raise ValueError(f"{field_name} must not be empty")

        normalized: list[ContentBlock] = []
        has_meaningful_content = False
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                raise TypeError(f"{field_name}[{index}] must be a dictionary")

            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise TypeError(f"{field_name}[{index}].text must be a string")
                normalized_block: ContentBlock = {"type": "text", "text": text}
                if text.strip():
                    has_meaningful_content = True
                normalized.append(normalized_block)
                continue

            if block_type == "image":
                url = block.get("url")
                path = block.get("path")
                mime_type = block.get("mime_type")
                detail = block.get("detail")

                if url is not None and not isinstance(url, str):
                    raise TypeError(f"{field_name}[{index}].url must be a string")
                if path is not None and not isinstance(path, str):
                    raise TypeError(f"{field_name}[{index}].path must be a string")
                if not url and not path:
                    raise ValueError(f"{field_name}[{index}] must include url or path")
                if url and path:
                    raise ValueError(f"{field_name}[{index}] cannot include both url and path")
                if mime_type is not None and not isinstance(mime_type, str):
                    raise TypeError(f"{field_name}[{index}].mime_type must be a string")
                if detail is not None and detail not in {"auto", "low", "high"}:
                    raise ValueError(
                        f"{field_name}[{index}].detail must be one of auto, low, or high",
                    )

                normalized_block = {"type": "image"}  # type: ignore[assignment]
                if url:
                    normalized_block["url"] = url
                if path:
                    normalized_block["path"] = path
                if mime_type:
                    normalized_block["mime_type"] = mime_type
                if detail:
                    normalized_block["detail"] = detail
                normalized.append(normalized_block)
                has_meaningful_content = True
                continue

            raise ValueError(
                f"{field_name}[{index}].type must be 'text' or 'image'",
            )

        if not has_meaningful_content:
            raise ValueError(f"{field_name} must contain text or image input")
        return normalized

    @staticmethod
    def _stringify_message_content(content: object) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)

        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            if block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
                    continue
            if block.get("type") == "image":
                parts.append("[image]")
                continue
            parts.append(str(block))
        return "\n".join(parts)
