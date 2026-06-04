"""OpenAI-compatible provider for the first simplified chatbot version."""

from __future__ import annotations

import base64
from collections.abc import Callable
from ipaddress import ip_address
import json
import re
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
        # Recover any main content the upstream parser misrouted into the
        # reasoning channel after `</think>`.
        reasoning_clean, leaked_content = _split_reasoning_channel(
            _extract_reasoning(response),
        )
        content = _extract_content(response)
        full_content = leaked_content + content if leaked_content else content
        return ProviderResponse(
            content=_strip_special_tokens(full_content),
            reasoning_content=_strip_special_tokens(reasoning_clean),
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
        on_reasoning_delta: Callable[[str], None] | None = None,
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
        reasoning_parts: list[str] = []
        usage: dict[str, int] = {}
        tool_buffers: dict[int, dict[str, str]] = {}
        finish_reason = "stop"
        # Routes reasoning-channel deltas, redirecting any post-`</think>` text
        # (misrouted main content) back to the content stream in real time.
        reasoning_router = _ReasoningContentRouter()
        async for chunk in stream:
            raw_reasoning = _extract_stream_reasoning_delta(chunk)
            reasoning_out, content_from_reasoning = reasoning_router.route(
                raw_reasoning,
            )
            if reasoning_out:
                reasoning_parts.append(reasoning_out)
                if on_reasoning_delta is not None:
                    on_reasoning_delta(reasoning_out)
            if content_from_reasoning:
                parts.append(content_from_reasoning)
                if on_delta is not None:
                    on_delta(content_from_reasoning)
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
            content=_strip_special_tokens("".join(parts)),
            reasoning_content=_strip_special_tokens("".join(reasoning_parts)),
            tool_calls=_finalize_stream_tool_calls(tool_buffers),
            finish_reason=finish_reason,
            usage=usage,
            raw_response=None,
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


def _extract_reasoning(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    return _extract_reasoning_text(message)


def _extract_stream_reasoning_delta(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""

    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    return _extract_reasoning_text(delta)


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


# Some thinking models (e.g. Qwen3 served behind certain reasoning parsers)
# mishandle the `<think>` / `</think>` delimiters on the reasoning channel.
# Two distinct failures are observed, both on multi-turn / tool-call replies
# where the model emits an empty thinking block:
#   1. The literal delimiter tokens leak into `reasoning_content`.
#   2. The actual answer (main content) is emitted *after* `</think>` on the
#      reasoning channel instead of on the content channel — i.e. the upstream
#      parser routes the answer into reasoning_content by mistake.
# `</think>` is therefore the boundary: text before it is genuine reasoning,
# text after it is main content that must be handed back to the content stream.
_THINK_TAG_RE = re.compile(r"</?think\s*>")
_THINK_CLOSE = "</think>"

# Some models (notably the DeepSeek family) delimit special control tokens with
# the full-width vertical bar U+FF5C, e.g. `<｜tool▁calls▁begin｜>`,
# `<｜tool▁sep｜>`, `<｜Assistant｜>`. When the upstream inference server fails
# to parse them into structured tool calls they leak verbatim into the content
# or reasoning channel — sometimes truncated, e.g. `<｜DSML｜tool_calls`. The
# full-width bar is effectively never present in real assistant prose, so we can
# safely drop any run starting with `<｜` up to an optional closing `>`.
_SPECIAL_TOKEN_RE = re.compile(r"<｜[^<>]*>?")


def _strip_think_tags(text: str) -> str:
    return _THINK_TAG_RE.sub("", text)


def _strip_special_tokens(text: str) -> str:
    return _SPECIAL_TOKEN_RE.sub("", text)


def _split_reasoning_channel(reasoning: str) -> tuple[str, str]:
    """Split raw reasoning-channel text into (reasoning, leaked_content).

    If a `</think>` delimiter is present, everything after it is main content
    the upstream parser misrouted; otherwise the whole thing is reasoning.
    Both parts are returned with stray think tags stripped.
    """
    if _THINK_CLOSE not in reasoning:
        return _strip_think_tags(reasoning), ""
    before, _, after = reasoning.partition(_THINK_CLOSE)
    return _strip_think_tags(before), _strip_think_tags(after)


class _ReasoningContentRouter:
    """Stateful router for streamed reasoning deltas.

    Tracks whether `</think>` has been seen on the reasoning channel. Once the
    thinking block is closed, any further reasoning-channel text is really main
    content and is routed to the content stream instead.
    """

    __slots__ = ("_closed",)

    def __init__(self) -> None:
        self._closed = False

    def route(self, reasoning_delta: str) -> tuple[str, str]:
        """Map a reasoning-channel delta to (reasoning_out, content_out)."""
        if not reasoning_delta:
            return "", ""
        if self._closed:
            return "", _strip_think_tags(reasoning_delta)
        if _THINK_CLOSE in reasoning_delta:
            before, _, after = reasoning_delta.partition(_THINK_CLOSE)
            self._closed = True
            return _strip_think_tags(before), _strip_think_tags(after)
        return _strip_think_tags(reasoning_delta), ""


def _extract_reasoning_text(source: Any) -> str:
    direct = _extract_text_field(_get_attr_or_key(source, "reasoning"))
    if direct:
        return direct
    direct = _extract_text_field(_get_attr_or_key(source, "reasoning_content"))
    if direct:
        return direct

    details = _get_attr_or_key(source, "reasoning_details")
    if not isinstance(details, list):
        return ""
    parts: list[str] = []
    for item in details:
        text = _extract_reasoning_detail_text(item)
        if text:
            parts.append(text)
    return "".join(parts)


def _extract_reasoning_detail_text(detail: Any) -> str:
    detail_type = _get_attr_or_key(detail, "type")
    text = _extract_text_field(_get_attr_or_key(detail, "text"))
    if not text:
        return ""
    if detail_type in {None, "", "reasoning.text"}:
        return text
    return ""


def _extract_text_field(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _extract_text_from_block(item)
            if text:
                parts.append(text)
        return "".join(parts)
    return ""


def _get_attr_or_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


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
