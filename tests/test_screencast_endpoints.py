import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("websockets")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from simplified_chatbot.server import endpoints_screencast


class _Config:
    browser = {"host": "0.0.0.0", "chromeDebuggingPort": 9333}


class _FakeChrome:
    def __init__(self, alive: bool) -> None:
        self.port = 9222
        self.proc = None if not alive else _Proc()


class _Proc:
    def poll(self):
        return None


class _NotifyRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, str | None]] = []

    async def notify(self, method: str, params: dict, *, session_id: str | None = None) -> None:
        self.calls.append((method, params, session_id))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(endpoints_screencast.router)
    app.state.config = _Config()
    app.state.chrome = _FakeChrome(alive=True)
    return app


def test_health_chrome_reports_running_process():
    client = TestClient(_build_app())
    response = client.get("/health/chrome")

    assert response.status_code == 200
    assert response.json() == {"chrome_alive": True, "cdp_port": 9222}


def test_list_tabs_uses_normalized_chrome_endpoint(monkeypatch):
    app = _build_app()

    async def fake_list_page_targets(host: str, port: int):
        assert host == "localhost"
        assert port == 9333
        return [
            {"id": "tab_1", "title": "Docs", "url": "https://example.com", "type": "page"},
            {"id": "tab_2", "title": "Ignored", "url": "chrome://flags", "type": "page"},
        ]

    monkeypatch.setattr(endpoints_screencast, "_list_page_targets", fake_list_page_targets)
    client = TestClient(app)
    response = client.get("/browser/tabs")

    assert response.status_code == 200
    assert response.json() == {
        "tabs": [
            {"targetId": "tab_1", "title": "Docs", "url": "https://example.com"},
            {"targetId": "tab_2", "title": "Ignored", "url": "chrome://flags"},
        ],
    }


def test_create_close_and_activate_tab_routes_call_cdp(monkeypatch):
    app = _build_app()
    calls: list[tuple[str, dict]] = []

    async def fake_one_shot(host: str, port: int, method: str, params: dict | None = None):
        assert host == "localhost"
        assert port == 9333
        calls.append((method, params or {}))
        if method == "Target.createTarget":
            return {"targetId": "tab_123"}
        return {}

    monkeypatch.setattr(endpoints_screencast, "_one_shot_cdp", fake_one_shot)
    client = TestClient(app)
    create_response = client.post("/browser/tabs", json={"url": "example.com"})
    close_response = client.delete("/browser/tabs/tab_123")
    activate_response = client.post("/browser/tabs/tab_123/activate")

    assert create_response.status_code == 200
    assert create_response.json() == {"targetId": "tab_123", "url": "https://example.com"}
    assert close_response.status_code == 200
    assert close_response.json() == {"targetId": "tab_123", "closed": True}
    assert activate_response.status_code == 200
    assert activate_response.json() == {"targetId": "tab_123", "activated": True}
    assert calls == [
        ("Target.createTarget", {"url": "https://example.com"}),
        ("Target.closeTarget", {"targetId": "tab_123"}),
        ("Target.activateTarget", {"targetId": "tab_123"}),
    ]


def test_dispatch_input_maps_mouse_and_keyboard_events():
    async def scenario() -> None:
        client = _NotifyRecorder()

        await endpoints_screencast.dispatch_input(
            client,
            "session-1",
            {
                "event": "mousedown",
                "x": 12,
                "y": 34,
                "button": "left",
                "clickCount": 2,
            },
        )
        await endpoints_screencast.dispatch_input(
            client,
            "session-1",
            {
                "event": "insertText",
                "text": "hello",
            },
        )

        assert client.calls == [
            (
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": 12.0,
                    "y": 34.0,
                    "modifiers": 0,
                    "button": "left",
                    "clickCount": 2,
                },
                "session-1",
            ),
            (
                "Input.insertText",
                {"text": "hello"},
                "session-1",
            ),
        ]

    asyncio.run(scenario())


def test_dispatch_navigate_normalizes_urls_and_history_actions():
    async def scenario() -> None:
        client = _NotifyRecorder()

        await endpoints_screencast.dispatch_navigate(
            client,
            "session-1",
            {"action": "goto", "url": "example.com"},
        )
        await endpoints_screencast.dispatch_navigate(
            client,
            "session-1",
            {"action": "back"},
        )

        assert client.calls == [
            (
                "Page.navigate",
                {"url": "https://example.com"},
                "session-1",
            ),
            (
                "Runtime.evaluate",
                {
                    "expression": "window.history.back()",
                    "awaitPromise": False,
                    "returnByValue": True,
                },
                "session-1",
            ),
        ]

    asyncio.run(scenario())


def test_sanitize_helpers_clamp_values():
    quality = endpoints_screencast._sanitize_quality(
        {"quality": 200, "maxWidth": 99999, "maxHeight": 10, "everyNthFrame": 0},
        endpoints_screencast.DEFAULT_SCREENCAST_PARAMS,
    )
    viewport = endpoints_screencast._sanitize_viewport(
        {"width": 99999, "height": 10, "deviceScaleFactor": 9, "mobile": True},
    )

    assert quality["quality"] == 100
    assert quality["maxWidth"] == 4096
    assert quality["maxHeight"] == 64
    assert quality["everyNthFrame"] == 1
    assert viewport == {
        "width": 4096,
        "height": 64,
        "deviceScaleFactor": 4.0,
        "mobile": True,
    }
    assert endpoints_screencast._sanitize_viewport({"width": 0, "height": 0}) is None


def test_screencast_websocket_returns_error_when_no_page_targets(monkeypatch):
    app = _build_app()

    async def fake_list_page_targets(host: str, port: int):
        assert host == "localhost"
        assert port == 9333
        return []

    monkeypatch.setattr(endpoints_screencast, "_list_page_targets", fake_list_page_targets)
    client = TestClient(app)
    with client.websocket_connect("/ws/browser/screencast") as websocket:
        payload = websocket.receive_json()

    assert payload == {"type": "error", "message": "no page target found"}
