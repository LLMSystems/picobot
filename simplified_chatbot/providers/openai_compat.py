"""OpenAI-compatible provider for the first simplified chatbot version."""

from __future__ import annotations

import base64
from collections.abc import Callable
from ipaddress import ip_address
import json
from mimetypes import guess_type
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from simplified_chatbot.agent.types import ContentBlock, Message, MessageContent
from simplified_chatbot.providers.base import (
    ChatProvider,
    ProviderResponse,
    ToolCallRequest,
)


class OpenAICompatProvider(ChatProvider):
    """Async-first wrapper around the OpenAI chat completions API."""

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
    ) -> None:
        from openai import AsyncOpenAI

        effective_key = api_key or ("not-needed" if _is_local_endpoint(api_base) else None)
        if not effective_key:
            raise ValueError(
                "api_key is required for non-local OpenAI-compatible providers",
            )

        self.api_key = effective_key
        self.api_base = api_base
        self._async_client = AsyncOpenAI(
            api_key=effective_key,
            base_url=api_base,
        )

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
        payload_messages = _serialize_messages(messages)
        # max_tokens is not for gpt-5 series, use max_completion_tokens instead
        if model.startswith("gpt-5"):
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": payload_messages,
                "max_completion_tokens": max_tokens,
                "timeout": timeout,
            }
        else:
            kwargs = {
                "model": model,
                "messages": payload_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
            }
        if tools:
            kwargs["tools"] = tools

        response = await self._async_client.chat.completions.create(**kwargs)
        return ProviderResponse(
            content=_extract_content(response),
            tool_calls=_extract_tool_calls(response),
            finish_reason=_extract_finish_reason(response),
            usage=_extract_usage(response),
            raw_response=response,
        )

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
        payload_messages = _serialize_messages(messages)
        # max_tokens is not for gpt-5 series, use max_completion_tokens instead
        if model.startswith("gpt-5"):
             kwargs: dict[str, Any] = {
                "model": model,
                "messages": payload_messages,
                "max_completion_tokens": max_tokens,
                "timeout": timeout,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
        else:
            kwargs: dict[str, Any] = {
                "model": model,
                "messages": payload_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
        if tools:
            kwargs["tools"] = tools

        stream = await self._async_client.chat.completions.create(**kwargs)

        parts: list[str] = []
        usage: dict[str, int] = {}
        chunks: list[Any] = []
        tool_buffers: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        async for chunk in stream:
            chunks.append(chunk)
            delta = _extract_stream_delta(chunk)
            if delta:
                parts.append(delta)
                if on_delta is not None:
                    on_delta(delta)

            chunk_usage = _extract_usage(chunk)
            if chunk_usage:
                usage = chunk_usage
            _accumulate_stream_tool_calls(chunk, tool_buffers)
            finish = _extract_finish_reason(chunk)
            if finish != "stop" or _has_stream_finish(chunk):
                finish_reason = finish

        return ProviderResponse(
            content="".join(parts),
            tool_calls=_finalize_stream_tool_calls(tool_buffers),
            finish_reason=finish_reason,
            usage=usage,
            raw_response=chunks,
        )


def _serialize_messages(messages: list[Message]) -> list[dict[str, Any]]:
    return [_serialize_message(message) for message in messages]


def _serialize_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": message["role"],
        "content": _serialize_message_content(message["content"]),
    }
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        payload["tool_calls"] = tool_calls
    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str):
        payload["tool_call_id"] = tool_call_id
    name = message.get("name")
    if isinstance(name, str):
        payload["name"] = name
    return payload


def _serialize_message_content(content: MessageContent) -> str | list[dict[str, Any]]:
    if isinstance(content, str):
        return content
    return [_serialize_content_block(block) for block in content]


def _serialize_content_block(block: ContentBlock) -> dict[str, Any]:
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        if not isinstance(text, str):
            raise TypeError("text content blocks must include a string text field")
        return {"type": "text", "text": text}

    if block_type == "image":
        detail = block.get("detail")
        resolved_detail = detail if detail in {"auto", "low", "high"} else "auto"
        image_url = _resolve_image_block_url(block)
        return {
            "type": "image_url",
            "image_url": {
                "url": image_url,
                "detail": resolved_detail,
            },
        }

    raise ValueError("Unsupported content block type")


def _resolve_image_block_url(block: ContentBlock) -> str:
    url = block.get("url")
    if isinstance(url, str) and url:
        return url

    path_value = block.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("image content blocks must include url or path")

    file_path = Path(path_value).expanduser()
    raw = file_path.read_bytes()
    mime_type = block.get("mime_type")
    if not isinstance(mime_type, str) or not mime_type:
        mime_type = guess_type(file_path.name)[0]
    if not mime_type:
        raise ValueError(
            f"Could not infer mime type for image path '{file_path}'. "
            "Provide mime_type explicitly.",
        )
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_content(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _extract_text_from_block(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _extract_tool_calls(response: Any) -> list[ToolCallRequest]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return []

    message = getattr(choices[0], "message", None)
    if message is None:
        return []

    raw_calls = getattr(message, "tool_calls", None) or []
    parsed: list[ToolCallRequest] = []
    for call in raw_calls:
        function = getattr(call, "function", None)
        if function is None:
            continue
        arguments = _parse_tool_arguments(getattr(function, "arguments", "{}"))
        parsed.append(
            ToolCallRequest(
                id=str(getattr(call, "id", "")),
                name=str(getattr(function, "name", "")),
                arguments=arguments,
            ),
        )
    return parsed


def _extract_finish_reason(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return "stop"
    finish_reason = getattr(choices[0], "finish_reason", None)
    return str(finish_reason or "stop")


def _extract_text_from_block(block: Any) -> str:
    if isinstance(block, dict):
        if isinstance(block.get("text"), str):
            return block["text"]
        if block.get("type") == "output_text":
            return str(block.get("text", ""))
        return ""

    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _extract_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        }

    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _extract_stream_delta(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""

    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""

    content = getattr(delta, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _extract_text_from_block(item)
            if text:
                parts.append(text)
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _accumulate_stream_tool_calls(
    chunk: Any,
    tool_buffers: dict[int, dict[str, str]],
) -> None:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return

    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return

    for tool_call in getattr(delta, "tool_calls", None) or []:
        index = getattr(tool_call, "index", None)
        if index is None:
            index = len(tool_buffers)
        buffer = tool_buffers.setdefault(
            int(index),
            {"id": "", "name": "", "arguments": ""},
        )
        tool_id = getattr(tool_call, "id", None)
        if isinstance(tool_id, str) and tool_id:
            buffer["id"] = tool_id
        function = getattr(tool_call, "function", None)
        if function is not None:
            function_name = getattr(function, "name", None)
            if isinstance(function_name, str) and function_name:
                buffer["name"] = function_name
            function_arguments = getattr(function, "arguments", None)
            if isinstance(function_arguments, str) and function_arguments:
                buffer["arguments"] += function_arguments


def _finalize_stream_tool_calls(
    tool_buffers: dict[int, dict[str, str]],
) -> list[ToolCallRequest]:
    tool_calls: list[ToolCallRequest] = []
    for index in sorted(tool_buffers):
        item = tool_buffers[index]
        tool_calls.append(
            ToolCallRequest(
                id=item["id"] or f"call_{index}",
                name=item["name"],
                arguments=_parse_tool_arguments(item["arguments"]),
            ),
        )
    return tool_calls


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments or "{}")
    except Exception:
        return {"raw": arguments}
    return parsed if isinstance(parsed, dict) else {"raw": arguments}


def _has_stream_finish(chunk: Any) -> bool:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return False
    return getattr(choices[0], "finish_reason", None) is not None


def _is_local_endpoint(api_base: str | None) -> bool:
    if not api_base:
        return False

    raw = api_base.strip().lower()
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    try:
        host = parsed.hostname
    except ValueError:
        return False

    if host in {"localhost", "host.docker.internal"}:
        return True
    if not host:
        return False

    try:
        addr = ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private
