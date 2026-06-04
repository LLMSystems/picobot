import asyncio
from pathlib import Path
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi.testclient import TestClient

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.runtime.local_runtime import LocalAgentRuntime
from simplified_chatbot.runtime.session_store import AioSQLiteSessionStore
from simplified_chatbot.server import app as app_module
from simplified_chatbot.server.app import create_app
from simplified_chatbot.server.browser import chrome_process


class _DummyChatbot:
    def __init__(self) -> None:
        self.config = ChatbotConfig(
            provider="openai_compat",
            model="gpt-5-mini",
        )


def test_create_app_lifespan_starts_and_stops_infrastructure(tmp_path, monkeypatch):
    events: list[str] = []
    chrome_instances: list[object] = []

    class FakeChrome:
        def __init__(self, port=None, host=None):
            self.port = port
            self.host = host
            self.proc = None
            chrome_instances.append(self)

        async def start(self):
            events.append("chrome.start")

        def stop(self):
            events.append("chrome.stop")

    class FakeAlerts:
        async def hydrate_from_db(self):
            events.append("alerts.hydrate")

    class FakeSnapshotTask:
        async def start(self):
            events.append("snapshot.start")

        async def stop(self):
            events.append("snapshot.stop")

    monkeypatch.setattr(app_module, "ChromeProcess", FakeChrome)

    runtime = LocalAgentRuntime(
        chatbot=_DummyChatbot(),
        store=AioSQLiteSessionStore(tmp_path / "sessions.db"),
    )
    app = create_app(runtime=runtime)
    app.state.alerts = FakeAlerts()
    app.state.snapshot_task = FakeSnapshotTask()

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200

    assert chrome_instances
    assert app.state.chrome is chrome_instances[0]
    assert events == [
        "chrome.start",
        "alerts.hydrate",
        "snapshot.start",
        "snapshot.stop",
        "chrome.stop",
    ]


def test_create_app_lifespan_does_not_block_on_mcp_startup(monkeypatch):
    events: list[str] = []

    class FakeChrome:
        def __init__(self, port=None, host=None):
            self.port = port
            self.host = host
            self.proc = None

        async def start(self):
            events.append("chrome.start")

        def stop(self):
            events.append("chrome.stop")

    class FakeRuntime:
        workspace_manager = None
        store = None

        async def ensure_mcp_connected_async(self):
            events.append("mcp.start")
            await asyncio.sleep(5)

        async def close_mcp_async(self):
            events.append("mcp.close")

    monkeypatch.setattr(app_module, "ChromeProcess", FakeChrome)

    app = create_app(runtime=FakeRuntime())
    started = time.perf_counter()
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0
    assert "mcp.start" in events
    assert "mcp.close" in events


def test_build_alert_service_returns_none_without_db():
    service = app_module._build_alert_service(
        metrics_db_path=None,
        alerts_config_path=None,
    )

    assert service is None


def test_build_alert_service_loads_rules_when_yaml_exists(tmp_path):
    db_path = tmp_path / "sessions.db"
    alerts_path = tmp_path / "alerts.yaml"
    alerts_path.write_text(
        "\n".join(
            [
                "rules:",
                "  - name: cpu_high",
                "    description: cpu",
                "    severity: warning",
                "    metric_path: system.cpu_percent",
                "    comparator: '>'",
                "    threshold: 80",
            ],
        ),
        encoding="utf-8",
    )

    service = app_module._build_alert_service(
        metrics_db_path=db_path,
        alerts_config_path=alerts_path,
    )

    assert service is not None
    assert [rule.name for rule in service.rules] == ["cpu_high"]
    assert service.store.db_path == db_path.resolve()


def test_chrome_process_kill_port_squatters_sends_sigkill(monkeypatch):
    proc = chrome_process.ChromeProcess(port=9333)
    calls: list[tuple[int, int]] = []
    sigkill = getattr(chrome_process.signal, "SIGKILL", 9)

    monkeypatch.setattr(proc, "_pids_on_port", lambda: [111, 222])
    monkeypatch.setattr(chrome_process.signal, "SIGKILL", sigkill, raising=False)
    monkeypatch.setattr(chrome_process.os, "kill", lambda pid, sig: calls.append((pid, sig)))

    proc._kill_port_squatters()

    assert calls == [
        (111, sigkill),
        (222, sigkill),
    ]


def test_chrome_process_start_builds_expected_command(monkeypatch):
    proc = chrome_process.ChromeProcess(binary="chrome-bin", port=9444, host="127.0.0.1")
    popen_calls: list[dict[str, object]] = []

    class FakePopen:
        def __init__(self, args, stdout, stderr, start_new_session, env):
            popen_calls.append(
                {
                    "args": list(args),
                    "stdout": stdout,
                    "stderr": stderr,
                    "start_new_session": start_new_session,
                    "env": dict(env),
                },
            )
            self.pid = 4321

    async def fake_wait_until_ready():
        popen_calls.append({"waited": True})

    monkeypatch.setattr(proc, "_kill_port_squatters", lambda: popen_calls.append({"killed": True}))
    monkeypatch.setattr(chrome_process.tempfile, "mkdtemp", lambda prefix: "TMP_PROFILE")
    monkeypatch.setattr(chrome_process.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(chrome_process.os, "getpgid", lambda pid: 9876, raising=False)
    monkeypatch.setattr(proc, "_wait_until_ready", fake_wait_until_ready)

    asyncio.run(proc.start())

    assert proc.user_data_dir == "TMP_PROFILE"
    assert proc._pgid == 9876
    assert popen_calls[0] == {"killed": True}
    assert popen_calls[1]["args"][0] == "chrome-bin"
    assert f"--remote-debugging-port={proc.port}" in popen_calls[1]["args"]
    assert "--user-data-dir=TMP_PROFILE" in popen_calls[1]["args"]
    assert popen_calls[1]["start_new_session"] is True
    assert popen_calls[1]["env"]["DISPLAY"] == ":99"
    assert popen_calls[2] == {"waited": True}


def test_chrome_process_wait_until_ready_retries_until_success(monkeypatch):
    proc = chrome_process.ChromeProcess(port=9555, host="127.0.0.1")
    sleep_calls: list[float] = []
    get_calls: list[tuple[str, float]] = []
    real_sleep = asyncio.sleep

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, timeout: float):
            self.calls += 1
            get_calls.append((url, timeout))
            if self.calls == 1:
                raise chrome_process.httpx.ConnectError("not ready")
            return FakeResponse(200)

    class FakeLoop:
        def __init__(self) -> None:
            self.now = 0.0

        def time(self) -> float:
            self.now += 0.1
            return self.now

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)
        await real_sleep(0)

    loop = FakeLoop()
    monkeypatch.setattr(chrome_process.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(chrome_process.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(chrome_process.asyncio, "get_event_loop", lambda: loop)

    asyncio.run(proc._wait_until_ready(timeout=1.0))

    assert get_calls[0] == ("http://127.0.0.1:9555/json/version", 1.0)
    assert len(get_calls) == 2
    assert sleep_calls == [0.2]


def test_chrome_process_stop_terminates_process_group_and_cleans_profile(tmp_path, monkeypatch):
    proc = chrome_process.ChromeProcess()
    proc._pgid = 2222
    proc.user_data_dir = str(tmp_path / "profile")
    Path(proc.user_data_dir).mkdir(parents=True)
    (Path(proc.user_data_dir) / "marker.txt").write_text("x", encoding="utf-8")
    killpg_calls: list[tuple[int, int]] = []
    wait_calls: list[int] = []
    sigkill = getattr(chrome_process.signal, "SIGKILL", 9)

    class FakePopen:
        def wait(self, timeout: int):
            wait_calls.append(timeout)

    proc.proc = FakePopen()  # type: ignore[assignment]
    monkeypatch.setattr(chrome_process.signal, "SIGKILL", sigkill, raising=False)
    monkeypatch.setattr(
        chrome_process.os,
        "killpg",
        lambda pgid, sig: killpg_calls.append((pgid, sig)),
        raising=False,
    )

    proc.stop()

    assert killpg_calls == [
        (2222, chrome_process.signal.SIGTERM),
        (2222, sigkill),
    ]
    assert wait_calls == [5]
    assert proc._pgid is None
    assert not Path(proc.user_data_dir).exists()
