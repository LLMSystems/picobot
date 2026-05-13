import asyncio

import pytest

from simplified_chatbot.providers.base import ChatProvider, ProviderResponse


class AsyncEchoProvider(ChatProvider):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def generate_async(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "method": "generate_async",
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                "tools": tools,
            },
        )
        return ProviderResponse(content="async-ok")

    async def stream_generate_async(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        on_delta=None,
        tools=None,
    ) -> ProviderResponse:
        self.calls.append(
            {
                "method": "stream_generate_async",
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                "tools": tools,
            },
        )
        if on_delta is not None:
            on_delta("A")
            on_delta("B")
        return ProviderResponse(content="AB")


def test_sync_generate_wrapper_calls_async_method():
    provider = AsyncEchoProvider()
    result = provider.generate(
        [{"role": "user", "content": "hello"}],
        model="gpt-4.1-mini",
        max_tokens=128,
        temperature=0.2,
        timeout=30.0,
    )
    assert result.content == "async-ok"
    assert provider.calls[0]["method"] == "generate_async"


def test_sync_stream_wrapper_calls_async_method_and_emits_delta():
    provider = AsyncEchoProvider()
    deltas: list[str] = []
    result = provider.stream_generate(
        [{"role": "user", "content": "hello"}],
        model="gpt-4.1-mini",
        max_tokens=128,
        temperature=0.2,
        timeout=30.0,
        on_delta=deltas.append,
    )
    assert result.content == "AB"
    assert deltas == ["A", "B"]
    assert provider.calls[0]["method"] == "stream_generate_async"


def test_sync_wrapper_raises_inside_event_loop():
    provider = AsyncEchoProvider()

    async def _call_sync_method() -> None:
        with pytest.raises(RuntimeError, match="Use await generate_async"):
            provider.generate(
                [{"role": "user", "content": "hello"}],
                model="gpt-4.1-mini",
                max_tokens=128,
                temperature=0.2,
                timeout=30.0,
            )

    asyncio.run(_call_sync_method())
