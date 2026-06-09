"""Tests for multi-agent type support: registry, tool filtering, prompts, store."""

import asyncio
import json
from pathlib import Path
from conftest import register_test_user

import pytest

from simplified_chatbot.agents.registry import AgentRegistry, KNOWN_TOOL_NAMES
from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.prompts.loader import load_system_prompt
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.tools.filesystem import build_default_tool_registry


def _write_chatbot_config(tmp_path: Path) -> Path:
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


def _write_registry(tmp_path: Path) -> Path:
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "default.md").write_text("Default agent prompt.", encoding="utf-8")
    (prompts / "coder.md").write_text("Coder agent prompt.", encoding="utf-8")
    manifest = tmp_path / "registry.yaml"
    manifest.write_text(
        "default: default\n"
        "agents:\n"
        "  - name: default\n"
        "    display_name: Default\n"
        "    description: all tools\n"
        "    prompt_file: prompts/default.md\n"
        "    tools: \"*\"\n"
        "  - name: coder\n"
        "    display_name: Coder\n"
        "    description: code only\n"
        "    prompt_file: prompts/coder.md\n"
        "    tools:\n"
        "      - read_file\n"
        "      - edit_file\n"
        "      - grep\n",
        encoding="utf-8",
    )
    return manifest


# --- Registry ---------------------------------------------------------------


def test_builtin_registry_loads_default_and_coder():
    registry = AgentRegistry.load()
    assert registry.default_name == "default"
    assert set(registry.names()) >= {"default", "coder", "researcher"}
    assert registry.allowed_tools("default") is None  # "*"
    assert "read_file" in registry.allowed_tools("coder")
    assert "spawn" not in registry.allowed_tools("coder")


def test_builtin_researcher_is_search_focused_read_only():
    registry = AgentRegistry.load()
    tools = set(registry.allowed_tools("researcher"))
    # search + read are available
    assert {"tavily_search", "web_fetch", "read_file"} <= tools
    # but code mutation / execution / delegation are not
    assert tools.isdisjoint({"exec", "edit_file", "apply_patch", "spawn"})
    assert registry.load_prompt("researcher").startswith("You are Picobot Researcher")


def test_registry_unknown_name_falls_back_to_default(tmp_path):
    registry = AgentRegistry.load(_write_registry(tmp_path))
    assert registry.get("does-not-exist").name == "default"
    assert registry.load_prompt(None) == "Default agent prompt."
    assert registry.load_prompt("coder") == "Coder agent prompt."


def test_registry_missing_manifest_falls_back_to_single_default(tmp_path):
    registry = AgentRegistry.load(tmp_path / "nope.yaml")
    assert registry.default_name == "default"
    assert registry.names() == ["default"]
    assert registry.allowed_tools("anything") is None


def test_registry_rejects_unknown_tool_name(tmp_path):
    manifest = _write_registry(tmp_path)
    manifest.write_text(
        "default: default\n"
        "agents:\n"
        "  - name: default\n"
        "    prompt_file: prompts/default.md\n"
        "    tools:\n"
        "      - not_a_real_tool\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown tool"):
        AgentRegistry.load(manifest)


def test_registry_rejects_missing_prompt_file(tmp_path):
    manifest = tmp_path / "registry.yaml"
    manifest.write_text(
        "agents:\n"
        "  - name: default\n"
        "    prompt_file: prompts/missing.md\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prompt file not found"):
        AgentRegistry.load(manifest)


# --- Tool filtering ---------------------------------------------------------


class _Dummy:
    pass


def test_known_tool_names_matches_main_profile_registry():
    registry = build_default_tool_registry(profile="main", subagent_manager=_Dummy())
    assert set(registry.tool_names) == set(KNOWN_TOOL_NAMES)


def test_allowed_tools_filters_registry():
    registry = build_default_tool_registry(
        profile="main",
        subagent_manager=_Dummy(),
        allowed_tools=["read_file", "edit_file", "grep"],
    )
    assert set(registry.tool_names) == {"read_file", "edit_file", "grep"}


def test_allowed_tools_none_keeps_all():
    registry = build_default_tool_registry(profile="main", subagent_manager=_Dummy())
    assert "spawn" in registry.tool_names
    assert "tavily_search" in registry.tool_names


def test_allowed_tools_empty_drops_all_builtins():
    registry = build_default_tool_registry(
        profile="main",
        subagent_manager=_Dummy(),
        allowed_tools=[],
    )
    assert registry.tool_names == []


# --- Prompt routing ---------------------------------------------------------


def test_load_system_prompt_routes_by_agent_type(tmp_path):
    registry = AgentRegistry.load(_write_registry(tmp_path))
    config = ChatbotConfig(model="gpt-4.1-mini")

    coder = load_system_prompt(config, agent_type="coder", registry=registry)
    default = load_system_prompt(config, agent_type="default", registry=registry)

    assert coder.startswith("Coder agent prompt.")
    assert default.startswith("Default agent prompt.")
    # runtime context is still appended per type
    assert "## Runtime Context" in coder


def test_load_system_prompt_none_matches_builtin_default():
    config = ChatbotConfig(model="gpt-4.1-mini")
    untyped = load_system_prompt(config)
    typed_default = load_system_prompt(config, agent_type="default")
    assert untyped == typed_default


def test_explicit_system_prompt_override_wins_over_agent_type(tmp_path):
    registry = AgentRegistry.load(_write_registry(tmp_path))
    config = ChatbotConfig(model="gpt-4.1-mini", system_prompt="Inline")
    prompt = load_system_prompt(config, agent_type="coder", registry=registry)
    assert prompt.startswith("Inline")


# --- Store persistence ------------------------------------------------------


def test_aiosqlite_store_persists_agent_type(tmp_path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")

    async def _run():
        created = await store.create_session("chat-1", {"title": "T", "agent_type": "coder"})
        metadata = await store.get_session_metadata("chat-1")
        renamed = await store.update_session_metadata("chat-1", {"title": "Renamed"})
        return created, metadata, renamed

    created, metadata, renamed = asyncio.run(_run())
    assert created["agent_type"] == "coder"
    assert metadata["agent_type"] == "coder"
    # updating an unrelated field preserves agent_type
    assert renamed["agent_type"] == "coder"
    assert renamed["title"] == "Renamed"


def test_aiosqlite_store_agent_type_defaults_to_none(tmp_path):
    pytest.importorskip("aiosqlite")
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")

    async def _run():
        await store.create_session("chat-1", {"title": "T"})
        return await store.get_session_metadata("chat-1")

    metadata = asyncio.run(_run())
    assert metadata["agent_type"] is None


# --- Chatbot wiring ---------------------------------------------------------


def test_for_workspace_applies_agent_type_prompt_and_tools(monkeypatch, tmp_path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    chatbot = SimplifiedChatbot.from_config(_write_chatbot_config(tmp_path))

    ws = tmp_path / "ws"
    ws.mkdir()
    coder = chatbot.for_workspace(ws, session_id="s-coder", agent_type="coder")
    default = chatbot.for_workspace(ws, session_id="s-default", agent_type=None)

    assert coder.system_prompt.startswith("You are Picobot Coder")
    assert "spawn" not in coder.tools.tool_names
    assert "tavily_search" not in coder.tools.tool_names
    assert "read_file" in coder.tools.tool_names
    # default keeps the full main toolset
    assert "spawn" in default.tools.tool_names
    assert set(default.tools.tool_names) == set(KNOWN_TOOL_NAMES)


# --- Runtime wiring ---------------------------------------------------------


def test_runtime_persists_and_reloads_agent_type(monkeypatch, tmp_path):
    pytest.importorskip("aiosqlite")
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")
    runtime = LocalAgentRuntime.from_config(
        _write_chatbot_config(tmp_path),
        store=store,
    )

    async def _run():
        summary = await runtime.create_session_async(
            title="T", session_id="sess-coder", agent_type="coder"
        )
        # simulate a fresh process: caches empty, prime from persisted metadata
        runtime._session_agent_types.clear()
        runtime._session_chatbots.clear()
        primed = await runtime._prime_session_agent_type_async("sess-coder")
        bot = runtime._get_chatbot_for_session("sess-coder")
        return summary, primed, bot

    summary, primed, bot = asyncio.run(_run())
    assert summary["agent_type"] == "coder"
    assert primed == "coder"
    assert "spawn" not in bot.tools.tool_names
    assert bot.system_prompt.startswith("You are Picobot Coder")


# --- HTTP endpoints ---------------------------------------------------------


def _build_app(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("aiosqlite")
    from fastapi.testclient import TestClient

    from simplified_chatbot.server.app import create_app

    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    store = AioSQLiteSessionStore(tmp_path / "sessions_async.db")
    runtime = LocalAgentRuntime.from_config(_write_chatbot_config(tmp_path), store=store)
    client = TestClient(create_app(runtime=runtime))
    register_test_user(client)
    return client
def test_get_agent_types_endpoint(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    body = client.get("/agent-types").json()
    assert body["default"] == "default"
    names = {item["name"] for item in body["agent_types"]}
    assert {"default", "coder"} <= names
    coder = next(item for item in body["agent_types"] if item["name"] == "coder")
    assert coder["display_name"]
    assert coder["description"]


def test_capabilities_exposes_agent_types_flag(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    features = client.get("/capabilities").json()["features"]
    assert features["agent_types"] is True


def test_create_session_with_agent_type(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post("/sessions", json={"title": "T", "agent_type": "coder"})
    assert resp.status_code == 200
    assert resp.json()["agent_type"] == "coder"


def test_create_session_without_agent_type_defaults_to_none(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post("/sessions", json={"title": "T"})
    assert resp.status_code == 200
    assert resp.json()["agent_type"] is None


def test_create_session_rejects_unknown_agent_type(monkeypatch, tmp_path):
    client = _build_app(monkeypatch, tmp_path)
    resp = client.post("/sessions", json={"title": "T", "agent_type": "wizard"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNKNOWN_AGENT_TYPE"
