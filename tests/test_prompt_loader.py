from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.prompts.loader import load_system_prompt


def test_system_prompt_override_wins():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        system_prompt="Inline prompt",
        system_prompt_file="ignored.md",
    )

    prompt = load_system_prompt(config)

    assert prompt.startswith("Inline prompt")
    assert "You are a practical coding assistant." not in prompt.splitlines()[0]


def test_system_prompt_file_is_resolved_relative_to_config(tmp_path):
    prompt_file = tmp_path / "prompts" / "custom.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("Custom prompt", encoding="utf-8")

    config = ChatbotConfig(
        model="gpt-4.1-mini",
        system_prompt_file="prompts/custom.md",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    prompt = load_system_prompt(config, config_path=config_path)

    assert prompt.startswith("Custom prompt")


def test_system_prompt_includes_active_skill_and_available_summary():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        enabled_skills=["math-tutor"],
    )

    prompt = load_system_prompt(config)

    assert "# Active Skills" in prompt
    assert "### Skill: concise-writer" in prompt
    assert "### Skill: math-tutor" in prompt
    assert "# Available Skills" in prompt
    assert "**tool-use-reminder**" in prompt


def test_system_prompt_includes_runtime_context_and_platform_policy(tmp_path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    prompt = load_system_prompt(config, config_path=config_path)

    assert "## Runtime Context" in prompt
    assert f"Current workspace: `{tmp_path.resolve()}`" in prompt
    assert "## Platform Policy" in prompt


def test_system_prompt_uses_explicit_workspace_when_provided(tmp_path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    session_workspace = tmp_path / "workspaces" / "session-1"
    session_workspace.mkdir(parents=True)

    prompt = load_system_prompt(
        config,
        config_path=config_path,
        workspace=session_workspace,
    )

    assert f"Current workspace: `{session_workspace.resolve()}`" in prompt
