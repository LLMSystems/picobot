from simplified_chatbot.tools.fake_tools import build_fake_tool_registry
from simplified_chatbot.tools.filesystem import build_default_tool_registry


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
    assert "write_file" in registry.tool_names
