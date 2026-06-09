import asyncio

from conftest import register_test_user

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.server.app import create_app
from simplified_chatbot.tools.ask_user_question import AskUserQuestionTool
from simplified_chatbot.tools.filesystem import build_default_tool_registry
from simplified_chatbot.tools.registry import ToolRegistry
from simplified_chatbot.tools.todo import TodoWriteTool


class _ToolOnlyChatbot:
    def __init__(self, tools: ToolRegistry) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
        )
        self.tools = tools


def test_ask_user_question_tool_waits_for_answer():
    async def scenario() -> None:
        tool = AskUserQuestionTool(timeout=1.0)
        task = asyncio.create_task(
            tool.execute(
                questions=[
                    {
                        "header": "Priority",
                        "question": "Which priority should we use?",
                        "multiSelect": False,
                        "options": [
                            {"label": "Fast", "description": "Ship quickly"},
                            {"label": "Safe", "description": "Be conservative"},
                        ],
                    },
                ],
            ),
        )
        await asyncio.sleep(0)

        assert tool.has_pending is True
        assert tool.answer({"priority": "Fast"}) is True

        result = await task
        assert result == {"ok": True, "answers": {"priority": "Fast"}}
        assert tool.has_pending is False
        assert tool.answer({"priority": "Safe"}) is False

    asyncio.run(scenario())


def test_ask_user_question_tool_times_out():
    async def scenario() -> None:
        tool = AskUserQuestionTool(timeout=0.01)
        result = await tool.execute(
            questions=[
                {
                    "header": "Mode",
                    "question": "Choose a mode",
                    "multiSelect": False,
                    "options": [
                        {"label": "A", "description": "First"},
                        {"label": "B", "description": "Second"},
                    ],
                },
            ],
        )
        assert result == {
            "ok": False,
            "error": "Timed out waiting for user response.",
        }
        assert tool.has_pending is False

    asyncio.run(scenario())


def test_runtime_answer_ask_user_question_resolves_pending_tool():
    async def scenario() -> None:
        tools = ToolRegistry()
        ask_tool = AskUserQuestionTool(timeout=1.0)
        tools.register(ask_tool)
        runtime = LocalAgentRuntime(chatbot=_ToolOnlyChatbot(tools))

        task = asyncio.create_task(
            ask_tool.execute(
                questions=[
                    {
                        "header": "Plan",
                        "question": "Which plan should we use?",
                        "multiSelect": False,
                        "options": [
                            {"label": "Small", "description": "Keep scope small"},
                            {"label": "Large", "description": "Do more work"},
                        ],
                    },
                ],
            ),
        )
        await asyncio.sleep(0)

        ok = await runtime.answer_ask_user_question("session_1", {"plan": "Small"})

        assert ok is True
        assert await task == {"ok": True, "answers": {"plan": "Small"}}

    asyncio.run(scenario())


def test_answer_ask_user_question_endpoint_returns_success(tmp_path):
    runtime = LocalAgentRuntime(
        chatbot=_ToolOnlyChatbot(build_default_tool_registry(workspace=tmp_path)),
    )

    async def fake_answer(session_id: str, answers: dict[str, object]) -> bool:
        assert session_id == "s1"
        assert answers == {"plan": "Safe"}
        return True

    runtime.answer_ask_user_question = fake_answer  # type: ignore[method-assign]
    asyncio.run(runtime.create_session_async(session_id="s1", user_id=1))
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)

    response = client.post(
        "/sessions/s1/ask_user_question/answer",
        json={"answers": {"plan": "Safe"}},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_answer_ask_user_question_endpoint_returns_404_when_no_pending(tmp_path):
    runtime = LocalAgentRuntime(
        chatbot=_ToolOnlyChatbot(build_default_tool_registry(workspace=tmp_path)),
    )

    async def fake_answer(session_id: str, answers: dict[str, object]) -> bool:
        assert session_id == "s1"
        assert answers == {"plan": "Safe"}
        return False

    runtime.answer_ask_user_question = fake_answer  # type: ignore[method-assign]
    asyncio.run(runtime.create_session_async(session_id="s1", user_id=1))
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)

    response = client.post(
        "/sessions/s1/ask_user_question/answer",
        json={"answers": {"plan": "Safe"}},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NO_PENDING_QUESTION"


def test_todo_write_tool_replaces_todos_and_reports_progress():
    async def scenario() -> None:
        tool = TodoWriteTool()
        result = await tool.execute(
            todos=[
                {
                    "content": "Scan modules",
                    "activeForm": "Scanning modules",
                    "status": "completed",
                },
                {
                    "content": "Write tests",
                    "activeForm": "Writing tests",
                    "status": "in_progress",
                },
            ],
        )

        assert result == {
            "ok": True,
            "todos": [
                {
                    "content": "Scan modules",
                    "activeForm": "Scanning modules",
                    "status": "completed",
                },
                {
                    "content": "Write tests",
                    "activeForm": "Writing tests",
                    "status": "in_progress",
                },
            ],
            "completed": 1,
            "total": 2,
        }
        assert tool.get_todos() == result["todos"]

    asyncio.run(scenario())


def test_todo_write_tool_rejects_multiple_in_progress_items():
    async def scenario() -> None:
        tool = TodoWriteTool()
        result = await tool.execute(
            todos=[
                {
                    "content": "A",
                    "activeForm": "Doing A",
                    "status": "in_progress",
                },
                {
                    "content": "B",
                    "activeForm": "Doing B",
                    "status": "in_progress",
                },
            ],
        )

        assert result["ok"] is False
        assert "Only one task may be in_progress" in result["error"]

    asyncio.run(scenario())


def test_default_registry_includes_interactive_tools(tmp_path):
    registry = build_default_tool_registry(workspace=tmp_path)

    assert "todo_write" in registry.tool_names
    assert "ask_user_question" in registry.tool_names
