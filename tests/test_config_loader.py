import json

from simplified_chatbot.config.loader import load_config


def test_load_config_resolves_env_vars_and_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "secret-key")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "apiKey": "${TEST_API_KEY}",
                "maxTokens": 2048,
                "systemPrompt": "You are terse.",
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.api_key == "secret-key"
    assert config.context_window_tokens == 32000
    assert config.max_tokens == 2048
    assert config.system_prompt == "You are terse."


def test_load_config_supports_workspace_root_dir_alias(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "workspaceRootDir": "agent-workspaces",
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.workspace_root_dir == "agent-workspaces"
