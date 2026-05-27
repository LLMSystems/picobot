import asyncio

from simplified_chatbot.agent.subagent import SubagentManager
from simplified_chatbot.tools.fake_tools import build_fake_tool_registry
from simplified_chatbot.tools.filesystem import build_default_tool_registry
from simplified_chatbot.tools.skills import ReadSkillTool


def test_fake_tool_registry_returns_openai_compatible_schemas():
    registry = build_fake_tool_registry()

    definitions = registry.get_definitions()

    assert [item["function"]["name"] for item in definitions] == [
        "calculator",
        "echo",
        "get_weather",
    ]
    assert definitions[0]["type"] == "function"


def test_registry_executes_fake_tool():
    registry = build_fake_tool_registry()

    result = registry.execute("calculator", {"expression": "3*7"})

    assert result == "21"


def test_default_tool_registry_includes_wave_1a_tools(tmp_path):
    registry = build_default_tool_registry(workspace=tmp_path)

    assert "exec" in registry.tool_names
    assert "tavily_search" in registry.tool_names
    assert "read_skill" in registry.tool_names
    assert "read_pdf" in registry.tool_names
    assert "read_docx" in registry.tool_names
    assert "read_xlsx" in registry.tool_names
    assert "write_file" in registry.tool_names


def test_subagent_tool_registry_profile_is_supported(tmp_path):
    registry = build_default_tool_registry(workspace=tmp_path, profile="subagent")

    assert "exec" in registry.tool_names
    assert "read_file" in registry.tool_names
    assert "grep" in registry.tool_names


def test_main_and_subagent_profiles_are_built_independently(tmp_path):
    main_registry = build_default_tool_registry(workspace=tmp_path, profile="main")
    subagent_registry = build_default_tool_registry(workspace=tmp_path, profile="subagent")

    assert main_registry is not subagent_registry
    assert main_registry.tool_names == subagent_registry.tool_names


def test_spawn_tool_registers_only_for_main_profile_when_manager_is_provided(tmp_path):
    manager = SubagentManager(lambda _workspace, _model: None)

    main_registry = build_default_tool_registry(
        workspace=tmp_path,
        profile="main",
        subagent_manager=manager,
        session_id="session_abc",
    )
    subagent_registry = build_default_tool_registry(
        workspace=tmp_path,
        profile="subagent",
        subagent_manager=manager,
    )

    assert "spawn" in main_registry.tool_names
    assert "list_subagents" in main_registry.tool_names
    assert "subagent_status" in main_registry.tool_names
    assert "subagent_wait" in main_registry.tool_names
    assert "spawn" not in subagent_registry.tool_names
    assert "list_subagents" not in subagent_registry.tool_names
    assert "subagent_status" not in subagent_registry.tool_names
    assert "subagent_wait" not in subagent_registry.tool_names
    assert main_registry.get("spawn")._workspace == tmp_path.resolve()
    assert main_registry.get("spawn")._parent_session_id == "session_abc"


def test_read_skill_tool_reads_builtin_skill():
    tool = ReadSkillTool()

    result = asyncio.run(tool.execute(name="tool-use-reminder"))

    assert "Prefer available tools when they make the answer more reliable." in result
    assert "Use tools before answering" in result
