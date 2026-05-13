import asyncio

import pytest

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ProviderResponse, ToolCallRequest
from simplified_chatbot.tools.fake_tools import build_fake_tool_registry
from simplified_chatbot.tools.filesystem import build_default_tool_registry


class DummyProvider:
    def __init__(self, content: str = "Hello back") -> None:
        self.content = content
        self.calls: list[dict] = []

    def generate(
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
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                "tools": tools,
            },
        )
        return ProviderResponse(
            content=self.content,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

    def stream_generate(
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
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "timeout": timeout,
                "stream": True,
                "tools": tools,
            },
        )
        if on_delta is not None:
            on_delta("Nice ")
            on_delta("to ")
            on_delta("stream")
        return ProviderResponse(
            content="Nice to stream",
            usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        )


def test_agent_loop_builds_messages_and_updates_history():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider(content="Nice to meet you")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    result = loop.run(
        "Hello",
        history=[{"role": "assistant", "content": "Previous reply"}],
    )

    sent_messages = provider.calls[0]["messages"]
    assert sent_messages[0] == {"role": "system", "content": "System prompt"}
    assert sent_messages[-1] == {"role": "user", "content": "Hello"}
    assert result.content == "Nice to meet you"
    assert result.messages == [
        {"role": "assistant", "content": "Previous reply"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Nice to meet you"},
    ]
    assert result.usage["total_tokens"] == 15


def test_agent_loop_rejects_system_messages_in_history():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider()
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    with pytest.raises(ValueError, match="user'.*assistant'.*tool"):
        loop.run(
            "Hello",
            history=[{"role": "system", "content": "Not allowed"}],
        )


def test_agent_loop_stream_returns_aggregated_result_and_emits_deltas():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider()
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")
    deltas: list[str] = []

    result = loop.run_stream(
        "Hello",
        on_delta=deltas.append,
    )

    assert deltas == ["Nice ", "to ", "stream"]
    assert result.content == "Nice to stream"
    assert result.messages[-1] == {"role": "assistant", "content": "Nice to stream"}


def test_agent_loop_run_async_returns_result():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider(content="Async hello")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    result = asyncio.run(loop.run_async("Hello async"))

    assert result.content == "Async hello"
    assert result.messages[-1]["content"] == "Async hello"


def test_agent_loop_stream_async_returns_result():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider()
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")
    deltas: list[str] = []

    result = asyncio.run(
        loop.run_stream_async("Hello async", on_delta=deltas.append),
    )

    assert result.content == "Nice to stream"
    assert deltas == ["Nice ", "to ", "stream"]


def test_agent_loop_sync_run_rejects_active_event_loop():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider(content="Nope")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    async def _call_sync_run() -> None:
        with pytest.raises(RuntimeError, match="Use await run_async"):
            loop.run("Hello")

    asyncio.run(_call_sync_run())


class ToolCallingProvider:
    def __init__(self) -> None:
        self.iteration = 0

    def generate(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        self.iteration += 1
        if self.iteration == 1:
            assert tools is not None
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="calculator",
                        arguments={"expression": "2+2"},
                    ),
                ],
                finish_reason="tool_calls",
            )

        assert messages[-1]["role"] == "tool"
        assert messages[-1]["content"] == "4"
        return ProviderResponse(
            content="The answer is 4.",
            finish_reason="stop",
            usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        )

    def stream_generate(self, *args, **kwargs):
        raise AssertionError("stream_generate should not be called in this test")


def test_agent_loop_executes_fake_tools_across_multiple_iterations():
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=4)
    loop = AgentLoop(
        provider=ToolCallingProvider(),
        config=config,
        system_prompt="System prompt",
        tools=build_fake_tool_registry(),
    )

    result = loop.run("What is 2+2?")

    assert result.content == "The answer is 4."
    assert result.tools_used == ["calculator"]
    assert result.stop_reason == "stop"
    assert result.messages[1]["role"] == "assistant"
    assert "tool_calls" in result.messages[1]
    assert result.messages[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "name": "calculator",
        "content": "4",
    }


def test_agent_loop_emits_tool_events():
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=4)
    loop = AgentLoop(
        provider=ToolCallingProvider(),
        config=config,
        system_prompt="System prompt",
        tools=build_fake_tool_registry(),
    )
    events: list[tuple[str, dict[str, object]]] = []

    result = loop.run(
        "What is 2+2?",
        on_event=lambda event, data: events.append((event, data)),
    )

    assert result.content == "The answer is 4."
    assert events == [
        (
            "tool_call_started",
            {
                "id": "call_1",
                "name": "calculator",
                "arguments": {"expression": "2+2"},
            },
        ),
        (
            "tool_call_finished",
            {
                "id": "call_1",
                "name": "calculator",
                "ok": True,
                "result": "4",
            },
        ),
    ]


class ReadFileToolCallingProvider:
    def __init__(self) -> None:
        self.iteration = 0

    def generate(
        self,
        messages,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
        tools=None,
    ) -> ProviderResponse:
        self.iteration += 1
        if self.iteration == 1:
            return ProviderResponse(
                content="",
                tool_calls=[
                    ToolCallRequest(
                        id="call_read_1",
                        name="read_file",
                        arguments={"path": "notes.txt"},
                    ),
                ],
                finish_reason="tool_calls",
            )
        assert messages[-1]["role"] == "tool"
        assert "1| hello tool loop" in messages[-1]["content"]
        return ProviderResponse(content="I read the file.", finish_reason="stop")

    def stream_generate(self, *args, **kwargs):
        raise AssertionError("stream_generate should not be called in this test")


def test_agent_loop_executes_read_file_tool(tmp_path):
    (tmp_path / "notes.txt").write_text("hello tool loop\n", encoding="utf-8")
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=3)
    loop = AgentLoop(
        provider=ReadFileToolCallingProvider(),
        config=config,
        system_prompt="System prompt",
        tools=build_default_tool_registry(workspace=tmp_path),
    )

    result = loop.run("Read notes.txt")

    assert result.content == "I read the file."
    assert result.tools_used == ["read_file"]
    assert result.messages[2]["role"] == "tool"
    assert result.messages[2]["name"] == "read_file"
    assert "1| hello tool loop" in result.messages[2]["content"]
