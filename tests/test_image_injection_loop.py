"""Agent loop tests for view_image-style image injection.

A tool returning a ToolResult with images must produce, in order:
  assistant(tool_calls) -> tool(text result) -> synthetic user(image blocks),
and emit an `image_injected` event. The synthetic user message carries the
images because OpenAI-compatible tool messages cannot.
"""

import asyncio

from simplified_chatbot.agent.loop import AgentLoop
from simplified_chatbot.agent.types import ToolResult
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.providers.base import ProviderResponse, ToolCallRequest
from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.registry import ToolRegistry


@tool_parameters(
    {
        "type": "object",
        "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        "required": ["paths"],
    },
)
class FakeViewImageTool(Tool):
    read_only = True

    def __init__(self, images: list[dict]) -> None:
        self._images = images

    @property
    def name(self) -> str:
        return "view_image"

    @property
    def description(self) -> str:
        return "fake view image"

    async def execute(self, paths=None, **kwargs) -> ToolResult:
        return ToolResult(text="Loaded image(s); attached below.", images=self._images)


class ViewImageCallingProvider:
    def __init__(self, tool_calls: list[ToolCallRequest]) -> None:
        self._tool_calls = tool_calls
        self._iteration = 0

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
        self._iteration += 1
        if self._iteration == 1:
            return ProviderResponse(
                content="",
                tool_calls=self._tool_calls,
                finish_reason="tool_calls",
            )
        return ProviderResponse(content="I can see it.", finish_reason="stop")

    async def stream_generate_async(self, *args, **kwargs):
        raise AssertionError("stream path not used")


def _build_loop(tool: Tool, provider) -> AgentLoop:
    registry = ToolRegistry()
    registry.register(tool)
    config = ChatbotConfig(provider="openai_compat", model="gpt-4o-mini")
    return AgentLoop(provider, config, system_prompt="sys", tools=registry)


def test_image_injection_appends_synthetic_user_message():
    images = [{"type": "image", "path": "chart.png", "detail": "auto"}]
    tool = FakeViewImageTool(images)
    provider = ViewImageCallingProvider(
        [ToolCallRequest(id="call_1", name="view_image", arguments={"paths": ["chart.png"]})],
    )
    loop = _build_loop(tool, provider)

    events: list[tuple[str, dict]] = []
    result = asyncio.run(
        loop.run_async("look at chart.png", on_event=lambda e, d: events.append((e, d))),
    )

    roles = [m["role"] for m in result.messages]
    # user, assistant(tool_calls), tool, injected-user, assistant(final)
    assert roles == ["user", "assistant", "tool", "user", "assistant"]

    tool_msg = result.messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == "Loaded image(s); attached below."

    injected = result.messages[3]
    assert injected["role"] == "user"
    assert injected["metadata"]["synthetic_image_injection"] is True
    # content = [strong note, image block]
    assert injected["content"][0]["type"] == "text"
    assert "NOT A MESSAGE FROM THE USER" in injected["content"][0]["text"]
    assert injected["content"][1] == {"type": "image", "path": "chart.png", "detail": "auto"}

    # injection must come AFTER the tool result
    assert roles.index("tool") < roles.index("user", 2)

    injected_events = [d for (e, d) in events if e == "image_injected"]
    assert len(injected_events) == 1
    assert injected_events[0]["images"][0]["path"] == "chart.png"


def test_image_injection_merges_multiple_images_into_one_message():
    images = [
        {"type": "image", "path": "a.png", "detail": "auto"},
        {"type": "image", "path": "b.png", "detail": "auto"},
    ]
    tool = FakeViewImageTool(images)
    provider = ViewImageCallingProvider(
        [ToolCallRequest(id="c1", name="view_image", arguments={"paths": ["a.png", "b.png"]})],
    )
    loop = _build_loop(tool, provider)

    result = asyncio.run(loop.run_async("look"))

    injected = [
        m
        for m in result.messages
        if m["role"] == "user" and m.get("metadata", {}).get("synthetic_image_injection")
    ]
    assert len(injected) == 1
    image_blocks = [b for b in injected[0]["content"] if b["type"] == "image"]
    assert [b["path"] for b in image_blocks] == ["a.png", "b.png"]


def test_no_injection_when_tool_returns_plain_string():
    @tool_parameters({"type": "object", "properties": {}, "required": []})
    class PlainTool(Tool):
        read_only = True

        @property
        def name(self) -> str:
            return "view_image"

        @property
        def description(self) -> str:
            return "plain"

        async def execute(self, **kwargs) -> str:
            return "no images here"

    provider = ViewImageCallingProvider(
        [ToolCallRequest(id="c1", name="view_image", arguments={})],
    )
    loop = _build_loop(PlainTool(), provider)

    result = asyncio.run(loop.run_async("hi"))
    roles = [m["role"] for m in result.messages]
    # No synthetic user injection: user, assistant, tool, assistant
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_normalize_tool_result_unwraps_envelope():
    envelope = ToolResult(text="summary text", images=[{"type": "image", "path": "x.png"}])
    assert AgentLoop._normalize_tool_result(envelope) == "summary text"
    assert AgentLoop._serialize_event_result(envelope) == "summary text"
