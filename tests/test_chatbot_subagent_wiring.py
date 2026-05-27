import json
from pathlib import Path

from simplified_chatbot.chatbot import SimplifiedChatbot


def _write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "apiKey": "test-key",
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_from_config_wires_spawn_tool_into_main_chatbot(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    config_path = _write_config(tmp_path)

    chatbot = SimplifiedChatbot.from_config(config_path)
    session_workspace = tmp_path / "workspaces" / "session-1"
    session_workspace.mkdir(parents=True)
    session_chatbot = chatbot.for_workspace(session_workspace, session_id="session-1")

    assert chatbot.subagent_manager is not None
    assert chatbot.supports_workspace_clone is True
    assert "spawn" in chatbot.tools.tool_names
    assert "spawn" in session_chatbot.tools.tool_names
    assert chatbot.tools.get("spawn")._manager is chatbot.subagent_manager
    assert session_chatbot.tools.get("spawn")._manager is chatbot.subagent_manager
    assert chatbot.tools.get("spawn")._parent_session_id is None
    assert session_chatbot.tools.get("spawn")._parent_session_id == "session-1"
    assert f"Current workspace: `{session_workspace.resolve()}`" in session_chatbot.system_prompt


def test_subagent_factory_uses_subagent_prompt_and_tool_profile(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    config_path = _write_config(tmp_path)

    chatbot = SimplifiedChatbot.from_config(config_path)
    sub_workspace = tmp_path / "workspaces" / "session-1" / ".subagents" / "sub_1234"
    sub_workspace.mkdir(parents=True)

    subagent_chatbot = chatbot.subagent_manager._chatbot_factory(sub_workspace, "gpt-5-mini")
    nested_workspace = sub_workspace / "nested"
    nested_workspace.mkdir()
    nested_subagent = subagent_chatbot.for_workspace(nested_workspace)

    assert "spawn" not in subagent_chatbot.tools.tool_names
    assert "spawn" not in nested_subagent.tools.tool_names
    assert subagent_chatbot.subagent_manager is None
    assert "You are a subagent working for the main Picobot agent." in subagent_chatbot.system_prompt
    assert "Do not spawn another subagent." in subagent_chatbot.system_prompt
    assert f"Current workspace: `{sub_workspace.resolve()}`" in subagent_chatbot.system_prompt
    assert f"Current workspace: `{nested_workspace.resolve()}`" in nested_subagent.system_prompt
