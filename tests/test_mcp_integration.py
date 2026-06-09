import asyncio
import json
import sys
import textwrap
import time
from pathlib import Path
from conftest import register_test_user

import pytest

pytest.importorskip("mcp")

from fastapi.testclient import TestClient

from simplified_chatbot.chatbot import SimplifiedChatbot
from simplified_chatbot.config.schema import MCPServerConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.server import app as app_module
from simplified_chatbot.server.app import create_app
from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.mcp import MCPConnectionManager
from simplified_chatbot.tools.registry import ToolRegistry
import simplified_chatbot.tools.mcp as mcp_module


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "value": {"type": "string"},
        },
        "required": ["value"],
    },
)
class _FakeMcpTool(Tool):
    @property
    def name(self) -> str:
        return "mcp_demo_fake"

    @property
    def description(self) -> str:
        return "Fake MCP tool"

    @property
    def display_name(self) -> str:
        return "demo::fake"

    async def execute(self, value: str, **kwargs):
        return f"fake:{value}"


class _FakeMcpManager:
    def register_tools_into(self, registry: ToolRegistry, *, profile: str | None = None) -> None:
        del profile
        registry.register(_FakeMcpTool())


class _FakeChrome:
    def __init__(self, port=None, host=None):
        self.port = port
        self.host = host
        self.proc = None

    async def start(self):
        return None

    def stop(self):
        return None


def _write_config(tmp_path: Path, extra: dict[str, object] | None = None) -> Path:
    payload: dict[str, object] = {
        "provider": "openai_compat",
        "model": "gpt-4.1-mini",
        "apiKey": "test-key",
    }
    if extra:
        payload.update(extra)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    return config_path


def _poll_mcp_status(client, predicate, *, timeout: float = 10.0, interval: float = 0.05) -> dict:
    """Poll ``/mcp/status`` until ``predicate(payload)`` holds or ``timeout`` elapses.

    MCP servers connect in a background task during app startup, so on slower
    machines the connect (subprocess spawn + handshake) is not finished by the
    time the first request lands. Tests must wait for the server to settle
    instead of reading status immediately, otherwise they race the connect.
    """
    deadline = time.perf_counter() + timeout
    payload = client.get("/mcp/status").json()
    while not predicate(payload):
        if time.perf_counter() > deadline:
            break
        time.sleep(interval)
        payload = client.get("/mcp/status").json()
    return payload


def _write_stdio_server(tmp_path: Path) -> Path:
    script = tmp_path / "mcp_stdio_server.py"
    script.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("demo")


            @mcp.tool()
            def greet(name: str) -> str:
                return f"hello {name}"


            @mcp.tool()
            def ping() -> str:
                return "pong"


            if __name__ == "__main__":
                mcp.run("stdio")
            """
        ),
        encoding="utf-8",
    )
    return script


def _write_stdio_server_with_resource_and_prompt(tmp_path: Path) -> Path:
    script = tmp_path / "mcp_stdio_server_resource_prompt.py"
    script.write_text(
        textwrap.dedent(
            """
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("demo-rp")


            @mcp.resource("memo://greeting", name="greeting_resource", description="Greeting resource")
            def greeting_resource():
                return "hello resource"


            @mcp.prompt(name="summarize", description="Summarize topic")
            def summarize(topic: str) -> str:
                return f"Summarize: {topic}"


            if __name__ == "__main__":
                mcp.run("stdio")
            """
        ),
        encoding="utf-8",
    )
    return script


def test_chatbot_wires_fake_mcp_tools_into_main_session_and_subagent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    config_path = _write_config(tmp_path)

    chatbot = SimplifiedChatbot.from_config(
        config_path,
        mcp_manager=_FakeMcpManager(),
    )
    session_workspace = tmp_path / "workspaces" / "session-1"
    session_workspace.mkdir(parents=True)
    session_chatbot = chatbot.for_workspace(session_workspace, session_id="session-1")

    sub_workspace = tmp_path / "workspaces" / "session-1" / ".subagents" / "sub_1234"
    sub_workspace.mkdir(parents=True)
    subagent_chatbot = chatbot.subagent_manager._chatbot_factory(sub_workspace, None)

    assert "mcp_demo_fake" in chatbot.tools.tool_names
    assert "mcp_demo_fake" in session_chatbot.tools.tool_names
    assert "mcp_demo_fake" in subagent_chatbot.tools.tool_names


def test_mcp_connection_manager_registers_stdio_tools_and_filters_enabled_tools(tmp_path: Path):
    server_script = _write_stdio_server(tmp_path)
    manager = MCPConnectionManager(
        {
            "demo": MCPServerConfig(
                command=sys.executable,
                args=[str(server_script)],
                enabled_tools=["greet"],
            )
        }
    )

    async def run() -> tuple[list[str], str]:
        await manager.connect_all()
        registry = ToolRegistry()
        manager.register_tools_into(registry)
        result = await registry.execute_async("mcp_demo_greet", {"name": "world"})
        await manager.aclose()
        return registry.tool_names, result

    tool_names, result = asyncio.run(run())

    assert "mcp_demo_greet" in tool_names
    assert "mcp_demo_ping" not in tool_names
    assert result == "hello world"


def test_runtime_from_config_exposes_mcp_tools_in_capabilities(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    server_script = _write_stdio_server(tmp_path)
    config_path = _write_config(
        tmp_path,
        {
            "mcpServers": {
                "demo": {
                    "command": sys.executable,
                    "args": [str(server_script)],
                    "enabledTools": ["greet"],
                }
            }
        },
    )

    runtime = LocalAgentRuntime.from_config(config_path)
    runtime.ensure_mcp_connected()
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.get("/capabilities")

    assert response.status_code == 200
    payload = response.json()
    tools = {item["name"]: item for item in payload["tools"]}
    assert "mcp_demo_greet" in tools
    assert tools["mcp_demo_greet"]["category"] == "mcp"


def test_mcp_status_endpoint_reports_connected_server_details(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)
    server_script = _write_stdio_server(tmp_path)
    config_path = _write_config(
        tmp_path,
        {
            "mcpServers": {
                "demo": {
                    "command": sys.executable,
                    "args": [str(server_script)],
                    "enabledTools": ["greet"],
                }
            }
        },
    )

    runtime = LocalAgentRuntime.from_config(config_path)
    app = create_app(runtime=runtime)

    with TestClient(app) as client:

        register_test_user(client)
        response = client.get("/mcp/status")
        assert response.status_code == 200
        payload = _poll_mcp_status(client, lambda p: p["connected_server_count"] == 1)

    assert payload["supported"] is True
    assert payload["reload_supported"] is True
    assert payload["enabled"] is True
    assert payload["configured_server_count"] == 1
    assert payload["connected_server_count"] == 1
    assert payload["connecting_server_count"] == 0
    assert payload["tool_count"] == 1
    assert payload["servers"][0]["name"] == "demo"
    assert payload["servers"][0]["connected"] is True
    assert payload["servers"][0]["connecting"] is False
    assert payload["servers"][0]["tool_names"] == ["mcp_demo_greet"]
    # The catalog lists every advertised tool, even the ones the enabledTools
    # filter dropped, so the UI can offer per-tool toggles.
    assert payload["servers"][0]["available_tools"] == ["greet", "ping"]


def test_mcp_status_endpoint_reports_connection_failures(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)
    config_path = _write_config(
        tmp_path,
        {
            "mcpServers": {
                "broken": {
                    "command": sys.executable,
                    "args": [str(tmp_path / "missing_mcp_server.py")],
                }
            }
        },
    )

    runtime = LocalAgentRuntime.from_config(config_path)
    app = create_app(runtime=runtime)

    with TestClient(app) as client:

        register_test_user(client)
        response = client.get("/mcp/status")
        assert response.status_code == 200
        payload = _poll_mcp_status(
            client,
            lambda p: p["servers"][0]["connecting"] is False
            and bool(p["servers"][0]["error"]),
        )

    assert payload["supported"] is True
    assert payload["enabled"] is True
    assert payload["configured_server_count"] == 1
    assert payload["connected_server_count"] == 0
    assert payload["connecting_server_count"] == 0
    assert payload["servers"][0]["name"] == "broken"
    assert payload["servers"][0]["connected"] is False
    assert payload["servers"][0]["connecting"] is False
    assert "Connection closed" in str(payload["servers"][0]["error"])


def test_mcp_reload_endpoint_reconciles_changed_server_tools(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)
    server_script = _write_stdio_server(tmp_path)
    config_path = _write_config(
        tmp_path,
        {
            "mcpServers": {
                "demo": {
                    "command": sys.executable,
                    "args": [str(server_script)],
                    "enabledTools": ["greet"],
                }
            }
        },
    )

    runtime = LocalAgentRuntime.from_config(config_path)
    app = create_app(runtime=runtime)

    with TestClient(app) as client:

        register_test_user(client)
        before = _poll_mcp_status(
            client,
            lambda p: p["servers"][0]["tool_names"] == ["mcp_demo_greet"],
        )
        assert before["servers"][0]["tool_names"] == ["mcp_demo_greet"]

        config_path.write_text(
            json.dumps(
                {
                    "provider": "openai_compat",
                    "model": "gpt-4.1-mini",
                    "apiKey": "test-key",
                    "mcpServers": {
                        "demo": {
                            "command": sys.executable,
                            "args": [str(server_script)],
                            "enabledTools": ["ping"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        reload_response = client.post("/mcp/reload")
        after = client.get("/mcp/status")
        capabilities = client.get("/capabilities")

    assert reload_response.status_code == 200
    reload_payload = reload_response.json()
    assert reload_payload["ok"] is True
    assert reload_payload["changed"] == ["demo"]
    assert reload_payload["tool_count"] == 1

    assert after.status_code == 200
    after_payload = after.json()
    assert after_payload["servers"][0]["tool_names"] == ["mcp_demo_ping"]

    tool_names = {item["name"] for item in capabilities.json()["tools"]}
    assert "mcp_demo_ping" in tool_names
    assert "mcp_demo_greet" not in tool_names


def test_mcp_reload_endpoint_returns_400_without_config_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)

    class _DummyChatbot:
        def __init__(self) -> None:
            self.config = type("Config", (), {"provider": "openai_compat", "model": "gpt-4.1-mini"})()

    runtime = LocalAgentRuntime(chatbot=_DummyChatbot())
    app = create_app(runtime=runtime)
    client = TestClient(app)
    register_test_user(client)
    response = client.post("/mcp/reload")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MCP_RELOAD_UNAVAILABLE"


def test_mcp_connection_manager_can_register_resources_and_prompts(tmp_path: Path):
    server_script = _write_stdio_server_with_resource_and_prompt(tmp_path)
    manager = MCPConnectionManager(
        {
            "demo": MCPServerConfig(
                command=sys.executable,
                args=[str(server_script)],
                include_resources=True,
                include_prompts=True,
            )
        }
    )

    async def run() -> tuple[list[str], str, str]:
        await manager.connect_all()
        registry = ToolRegistry()
        manager.register_tools_into(registry)
        resource_result = await registry.execute_async(
            "mcp_demo_resource_greeting_resource",
            {},
        )
        prompt_result = await registry.execute_async(
            "mcp_demo_prompt_summarize",
            {"topic": "MCP"},
        )
        await manager.aclose()
        return registry.tool_names, resource_result, prompt_result

    tool_names, resource_result, prompt_result = asyncio.run(run())

    assert "mcp_demo_resource_greeting_resource" in tool_names
    assert "mcp_demo_prompt_summarize" in tool_names
    assert resource_result == "hello resource"
    assert prompt_result == "Summarize: MCP"


def test_mcp_connection_manager_times_out_stuck_server(monkeypatch):
    manager = MCPConnectionManager(
        {
            "github": MCPServerConfig(
                type="streamableHttp",
                url="https://api.githubcopilot.com/mcp/",
                tool_timeout=1,
            )
        }
    )

    async def _hanging_connect(_manager, _server_name, _cfg):
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(mcp_module, "_connect_single_server", _hanging_connect)

    async def run() -> tuple[float, dict[str, object]]:
        started = time.perf_counter()
        await manager.connect_all()
        elapsed = time.perf_counter() - started
        return elapsed, manager.diagnostics()

    elapsed, diagnostics = asyncio.run(run())

    assert elapsed < 2.5
    assert diagnostics["connected_server_count"] == 0
    assert diagnostics["connecting_server_count"] == 0
    assert diagnostics["servers"][0]["error"] == "Connection timed out after 1s"


def test_mcp_connection_manager_times_out_even_when_connect_task_ignores_cancellation(monkeypatch):
    manager = MCPConnectionManager(
        {
            "exampleRemote": MCPServerConfig(
                type="streamableHttp",
                url="https://example-server.modelcontextprotocol.io/mcp",
                tool_timeout=1,
            )
        }
    )

    async def _stubborn_connect(_manager, _server_name, _cfg):
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(5)
        return None

    monkeypatch.setattr(mcp_module, "_connect_single_server", _stubborn_connect)

    async def run() -> tuple[float, dict[str, object]]:
        started = time.perf_counter()
        await manager.connect_all()
        elapsed = time.perf_counter() - started
        return elapsed, manager.diagnostics()

    elapsed, diagnostics = asyncio.run(run())

    assert elapsed < 2.5
    assert diagnostics["connected_server_count"] == 0
    assert diagnostics["connecting_server_count"] == 0
    assert diagnostics["servers"][0]["connecting"] is False
    assert diagnostics["servers"][0]["error"] == "Connection timed out after 1s"


def test_mcp_status_reports_connecting_server_while_background_connect_is_pending(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)

    config_path = _write_config(
        tmp_path,
        {
            "mcpServers": {
                "exampleRemote": {
                    "type": "streamableHttp",
                    "url": "https://example-server.modelcontextprotocol.io/mcp",
                    "includeResources": True,
                    "includePrompts": True,
                    "toolTimeout": 5,
                }
            }
        },
    )

    start_event = asyncio.Event()
    release_event = asyncio.Event()

    async def _slow_connect(_manager, _server_name, _cfg):
        start_event.set()
        await release_event.wait()
        return None

    monkeypatch.setattr(mcp_module, "_connect_single_server", _slow_connect)

    runtime = LocalAgentRuntime.from_config(config_path)
    app = create_app(runtime=runtime)

    with TestClient(app) as client:

        register_test_user(client)
        started = time.perf_counter()
        while not start_event.is_set():
            if time.perf_counter() - started > 2:
                raise AssertionError("background MCP connect did not start")
            time.sleep(0.01)
        response = client.get("/mcp/status")
        release_event.set()

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected_server_count"] == 0
    assert payload["connecting_server_count"] == 1
    assert payload["servers"][0]["name"] == "exampleRemote"
    assert payload["servers"][0]["connected"] is False
    assert payload["servers"][0]["connecting"] is True
    assert payload["servers"][0]["error"] is None


def test_mcp_upsert_and_delete_server_endpoints(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("simplified_chatbot.chatbot.build_provider", lambda _config: object())
    monkeypatch.setattr(app_module, "ChromeProcess", _FakeChrome)
    server_script = _write_stdio_server(tmp_path)
    config_path = _write_config(tmp_path, {"apiKey": "${MY_KEY}"})
    monkeypatch.setenv("MY_KEY", "dummy")

    runtime = LocalAgentRuntime.from_config(config_path)
    app = create_app(runtime=runtime)

    with TestClient(app) as client:

        register_test_user(client)
        created = client.put(
            "/mcp/servers/demo",
            json={
                "type": "stdio",
                "command": sys.executable,
                "args": [str(server_script)],
                "enabledTools": ["greet"],
            },
        )
        assert created.status_code == 200, created.json()
        payload = _poll_mcp_status(client, lambda p: p["connected_server_count"] == 1)
        assert payload["servers"][0]["tool_names"] == ["mcp_demo_greet"]

        # Raw GET round-trips camelCase keys (matches the on-disk convention).
        raw = client.get("/mcp/servers").json()
        assert raw["servers"]["demo"]["enabledTools"] == ["greet"]

        # The unrelated ${MY_KEY} placeholder is never resolved on write.
        on_disk = json.loads(config_path.read_text(encoding="utf-8"))
        assert on_disk["apiKey"] == "${MY_KEY}"
        assert on_disk["mcpServers"]["demo"]["command"] == sys.executable

        # stdio without a command is rejected with a 400, not persisted.
        invalid = client.put("/mcp/servers/bad", json={"type": "stdio"})
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "MCP_SERVER_INVALID"

        deleted = client.delete("/mcp/servers/demo")
        assert deleted.status_code == 200
        assert deleted.json()["configured_server_count"] == 0
        assert "demo" not in json.loads(config_path.read_text(encoding="utf-8")).get(
            "mcpServers", {}
        )

        missing = client.delete("/mcp/servers/demo")
        assert missing.status_code == 404
