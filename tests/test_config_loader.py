import json

import pytest

from simplified_chatbot.config.loader import load_config
from simplified_chatbot.providers.factory import build_provider


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


def test_load_config_supports_available_models_alias(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "availableModels": ["gpt-4.1-mini", "gpt-5-mini"],
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.available_models == ["gpt-4.1-mini", "gpt-5-mini"]


def test_load_config_supports_memory_aliases(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "memoryEnabled": True,
                "memoryCompressionRatio": 0.65,
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.memory_enabled is True
    assert config.memory_compression_ratio == 0.65


def test_load_config_supports_mcp_server_aliases_and_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_TOKEN", "secret-token")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "mcpServers": {
                    "demo": {
                        "command": "python",
                        "args": ["demo.py"],
                        "toolTimeout": 45,
                        "enabledTools": ["greet"],
                        "headers": {
                            "Authorization": "Bearer ${MCP_TOKEN}",
                        },
                    }
                },
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert "demo" in config.mcp_servers
    server = config.mcp_servers["demo"]
    assert server.command == "python"
    assert server.args == ["demo.py"]
    assert server.tool_timeout == 45
    assert server.enabled_tools == ["greet"]
    assert server.headers == {"Authorization": "Bearer secret-token"}


def test_load_config_requires_default_model_to_exist_in_available_models():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="available_models"):
        load_config_payload(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "availableModels": ["gpt-5-mini"],
            },
        )


def test_load_config_supports_subagent_model_alias(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "subagentModel": "gpt-4.1-nano",
            },
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.subagent_model == "gpt-4.1-nano"


def test_load_config_requires_subagent_model_to_exist_in_available_models():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="subagent_model"):
        load_config_payload(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
                "availableModels": ["gpt-4.1-mini"],
                "subagentModel": "gpt-4.1-nano",
            },
        )


def test_load_config_auto_loads_dotenv_from_parent_directory(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    configs_dir = project_root / "configs"
    configs_dir.mkdir()
    (project_root / ".env").write_text(
        "OPENAI_API_KEY=dotenv-secret\n",
        encoding="utf-8",
    )
    config_path = configs_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "provider": "openai_compat",
                "model": "gpt-4.1-mini",
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    load_config(config_path)

    assert "OPENAI_API_KEY" in __import__("os").environ
    assert __import__("os").environ["OPENAI_API_KEY"] == "dotenv-secret"


def test_build_provider_uses_env_api_key_when_config_omits_it(monkeypatch):
    captured: dict[str, str | None] = {}

    class _FakeProvider:
        def __init__(self, api_key: str | None, api_base: str | None = None) -> None:
            captured["api_key"] = api_key
            captured["api_base"] = api_base

    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    monkeypatch.setattr(
        "simplified_chatbot.providers.factory.OpenAICompatProvider",
        _FakeProvider,
    )

    config = load_config_payload(
        {
            "provider": "openai_compat",
            "model": "gpt-4.1-mini",
        },
    )

    provider = build_provider(config)

    assert isinstance(provider, _FakeProvider)
    assert captured["api_key"] == "env-secret"
    assert captured["api_base"] is None


def load_config_payload(payload: dict[str, object]):
    from simplified_chatbot.config.schema import ChatbotConfig

    return ChatbotConfig.model_validate(payload)
