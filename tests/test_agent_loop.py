import asyncio

import pytest

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.agent.types import Message
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


def test_agent_loop_build_messages_accepts_multimodal_user_content():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider(content="Nice to meet you")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    messages = loop.build_messages(
        [
            {"type": "text", "text": "Describe this image"},
            {"type": "image", "url": "https://example.com/cat.png", "detail": "high"},
        ],
        history=[{"role": "assistant", "content": "Previous reply"}],
    )

    assert messages[0] == {"role": "system", "content": "System prompt"}
    assert messages[1] == {"role": "assistant", "content": "Previous reply"}
    assert messages[2] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image"},
            {"type": "image", "url": "https://example.com/cat.png", "detail": "high"},
        ],
    }


def test_agent_loop_accepts_system_messages_in_history_and_preserves_metadata():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider(content="Continued")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    result = loop.run(
        "Hello",
        history=[
            {
                "role": "system",
                "content": "Internal subagent result",
                "metadata": {"internal": True, "source": "subagent"},
                "id": "msg_internal",
                "created_at": "2026-01-01T00:00:00Z",
            }
        ],
    )

    sent_messages = provider.calls[0]["messages"]
    assert sent_messages[1]["role"] == "system"
    assert sent_messages[1]["content"] == "Internal subagent result"
    assert result.messages[0]["metadata"] == {"internal": True, "source": "subagent"}
    assert result.messages[0]["id"] == "msg_internal"
    assert result.messages[0]["created_at"] == "2026-01-01T00:00:00Z"


def test_agent_loop_rejects_invalid_history_role():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider()
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    with pytest.raises(ValueError, match="system'.*user'.*assistant'.*tool"):
        loop.run("Hello", history=[{"role": "narrator", "content": "Not allowed"}])


def test_agent_loop_rejects_invalid_multimodal_user_content():
    config = ChatbotConfig(model="gpt-4.1-mini")
    provider = DummyProvider()
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    with pytest.raises(ValueError, match="must include url or path"):
        loop.build_messages(
            [{"type": "image"}],
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


def test_agent_loop_model_override_is_passed_to_provider():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        available_models=["gpt-4.1-mini", "gpt-5-mini"],
    )
    provider = DummyProvider(content="Override hello")
    loop = AgentLoop(provider=provider, config=config, system_prompt="System prompt")

    result = loop.run("Hello override", model_override="gpt-5-mini")

    assert provider.calls[0]["model"] == "gpt-5-mini"
    assert result.model == "gpt-5-mini"


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
    # Filter out `llm_call_finished` (instrumentation events emitted around
    # every provider call) — this test is asserting the tool event contract.
    tool_events = [e for e in events if e[0] != "llm_call_finished"]
    assert tool_events == [
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


class ContinuationProvider:
    def __init__(self) -> None:
        self.iteration = 0
        self.calls: list[list[Message]] = []

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
        self.calls.append(messages)
        self.iteration += 1
        if self.iteration == 1:
            assert messages[-1]["role"] == "system"
            assert messages[-1]["content"] == "Internal subagent result"
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
            content="I used the subagent result and finished the task.",
            finish_reason="stop",
            usage={"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
        )

    async def stream_generate_async(self, *args, **kwargs):
        raise AssertionError("stream_generate_async should not be called in this test")


def test_agent_loop_continue_async_does_not_append_user_message_and_can_call_tools():
    config = ChatbotConfig(model="gpt-4.1-mini", max_iterations=4)
    provider = ContinuationProvider()
    loop = AgentLoop(
        provider=provider,
        config=config,
        system_prompt="System prompt",
        tools=build_fake_tool_registry(),
    )
    history: list[Message] = [
        {
            "role": "system",
            "content": "Internal subagent result",
            "metadata": {"internal": True, "source": "subagent"},
        }
    ]

    result = asyncio.run(loop.continue_async(history))

    assert result.content == "I used the subagent result and finished the task."
    assert result.tools_used == ["calculator"]
    assert result.messages[0]["role"] == "system"
    assert result.messages[0]["content"] == "Internal subagent result"
    assert all(
        not (
            message["role"] == "user"
            and message["content"] == "Internal subagent result"
        )
        for message in provider.calls[0]
    )


def test_agent_loop_continue_async_respects_model_override_and_emits_tool_events():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        available_models=["gpt-4.1-mini", "gpt-5-mini"],
        max_iterations=4,
    )
    provider = ContinuationProvider()
    loop = AgentLoop(
        provider=provider,
        config=config,
        system_prompt="System prompt",
        tools=build_fake_tool_registry(),
    )
    events: list[tuple[str, dict[str, object]]] = []

    result = asyncio.run(
        loop.continue_async(
            [{"role": "system", "content": "Internal subagent result"}],
            model_override="gpt-5-mini",
            on_event=lambda event, data: events.append((event, data)),
        )
    )

    assert result.model == "gpt-5-mini"
    tool_events = [e for e in events if e[0] != "llm_call_finished"]
    assert tool_events == [
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
