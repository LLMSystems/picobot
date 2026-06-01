import json
import logging
from typing import Any
import asyncio
import contextlib

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from pydantic import BaseModel


logger = logging.getLogger("screencast.router")


def _chrome_endpoint(request: Request) -> tuple[str, int]:
    """Resolve Chrome CDP host/port from app config, with sensible fallbacks."""
    config = getattr(request.app.state, "config", None)
    host = "localhost"
    port = 9222
    if config is not None and getattr(config, "browser", None):
        host = config.browser.get("host", host) or host
        port = int(config.browser.get("chromeDebuggingPort", port) or port)
    # /json from "0.0.0.0" is unreliable client-side; treat it as localhost.
    if host in ("0.0.0.0", "::"):
        host = "localhost"
    return host, port


async def _list_page_targets(host: str, port: int) -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{host}:{port}/json", timeout=3.0)
        resp.raise_for_status()
        targets = resp.json()
    return [t for t in targets if t.get("type") == "page"]


async def _browser_ws_url(host: str, port: int) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{host}:{port}/json/version", timeout=3.0)
        resp.raise_for_status()
        data = resp.json()
    url = data.get("webSocketDebuggerUrl")
    if not url:
        raise RuntimeError("chrome did not return webSocketDebuggerUrl")
    return url


class CdpBrowserClient:
    """Browser-level CDP client with flat-session multiplexing.

    Single websocket to Chrome's browser target. Commands and events carry
    `sessionId` to route to/from per-page sessions attached via
    `Target.attachToTarget(flatten=True)`. This is the foundation that lets
    us add per-tab streaming (option B/C) later without changing wire format.
    """

    def __init__(self, ws: Any):
        self.ws = ws
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self.event_handler: Any = None  # async (msg: dict) -> None

    async def _send(self, payload: dict) -> None:
        async with self._lock:
            await self.ws.send(json.dumps(payload))

    async def call(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 10.0,
    ) -> dict:
        cmd_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": cmd_id, "method": method}
        if params is not None:
            payload["params"] = params
        if session_id is not None:
            payload["sessionId"] = session_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[cmd_id] = fut
        try:
            await self._send(payload)
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(cmd_id, None)

    async def notify(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> None:
        """Fire-and-forget — used for high-frequency input events."""
        cmd_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"id": cmd_id, "method": method}
        if params is not None:
            payload["params"] = params
        if session_id is not None:
            payload["sessionId"] = session_id
        await self._send(payload)

    async def pump(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_id = msg.get("id")
                if msg_id is not None:
                    fut = self._pending.pop(msg_id, None)
                    if fut is not None and not fut.done():
                        if "error" in msg:
                            err = msg["error"]
                            fut.set_exception(
                                RuntimeError(err.get("message", "cdp error"))
                            )
                        else:
                            fut.set_result(msg.get("result", {}))
                    continue
                handler = self.event_handler
                if handler is not None:
                    try:
                        await handler(msg)
                    except Exception:
                        logger.exception("event handler failed")
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("cdp connection closed"))
            self._pending.clear()


async def _one_shot_cdp(
    host: str, port: int, method: str, params: dict | None = None
) -> dict:
    """Open a short-lived browser-level CDP ws to run a single command."""
    url = await _browser_ws_url(host, port)
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(
            json.dumps({"id": 1, "method": method, "params": params or {}})
        )
        # Drain until we see our response; ignore unrelated events.
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "cdp error"))
                return msg.get("result", {})


router = APIRouter()


@router.get("/health/chrome")
async def health(request: Request) -> dict[str, Any]:
    chrome = request.app.state.chrome
    alive = chrome is not None and chrome.proc is not None and chrome.proc.poll() is None
    return {"chrome_alive": alive, "cdp_port": chrome.port}


# ---------- Tab management REST ----------


class CreateTabRequest(BaseModel):
    url: str | None = None


def _tab_payload(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "targetId": t.get("id"),
        "title": t.get("title", "") or "",
        "url": t.get("url", "") or "",
    }


@router.get("/browser/tabs")
async def list_tabs(request: Request) -> dict[str, Any]:
    host, port = _chrome_endpoint(request)
    try:
        targets = await _list_page_targets(host, port)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"tabs": [_tab_payload(t) for t in targets]}


@router.post("/browser/tabs")
async def create_tab(request: Request, body: CreateTabRequest) -> dict[str, Any]:
    host, port = _chrome_endpoint(request)
    url = (body.url or "about:blank").strip() or "about:blank"
    if not url.startswith(("http://", "https://", "about:", "file://", "chrome://")):
        url = f"https://{url}"
    try:
        result = await _one_shot_cdp(
            host, port, "Target.createTarget", {"url": url}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    target_id = result.get("targetId")
    if not target_id:
        raise HTTPException(status_code=502, detail="createTarget returned no targetId")
    return {"targetId": target_id, "url": url}


@router.delete("/browser/tabs/{target_id}")
async def close_tab(request: Request, target_id: str) -> dict[str, Any]:
    host, port = _chrome_endpoint(request)
    try:
        await _one_shot_cdp(
            host, port, "Target.closeTarget", {"targetId": target_id}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"targetId": target_id, "closed": True}


@router.post("/browser/tabs/{target_id}/activate")
async def activate_tab(request: Request, target_id: str) -> dict[str, Any]:
    host, port = _chrome_endpoint(request)
    try:
        await _one_shot_cdp(
            host, port, "Target.activateTarget", {"targetId": target_id}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"targetId": target_id, "activated": True}


# ---------- Input dispatch ----------


MOUSE_EVENT_TYPE_MAP = {
    "mousedown": "mousePressed",
    "mouseup": "mouseReleased",
    "mousemove": "mouseMoved",
    "wheel": "mouseWheel",
}

ALLOWED_MOUSE_BUTTONS = {"left", "middle", "right", "none"}


async def dispatch_input(
    client: CdpBrowserClient, session_id: str, msg: dict
) -> None:
    event = msg.get("event")

    if event in ("mousedown", "mouseup", "mousemove", "wheel"):
        params: dict[str, Any] = {
            "type": MOUSE_EVENT_TYPE_MAP[event],
            "x": float(msg.get("x", 0) or 0),
            "y": float(msg.get("y", 0) or 0),
            "modifiers": int(msg.get("modifiers", 0) or 0),
        }
        if event in ("mousedown", "mouseup"):
            button = msg.get("button", "left")
            if button not in ALLOWED_MOUSE_BUTTONS:
                button = "left"
            params["button"] = button
            params["clickCount"] = int(msg.get("clickCount", 1) or 1)
        elif event == "wheel":
            params["button"] = "none"
            params["deltaX"] = float(msg.get("deltaX", 0) or 0)
            params["deltaY"] = float(msg.get("deltaY", 0) or 0)
        else:  # mousemove
            params["button"] = "none"
        await client.notify(
            "Input.dispatchMouseEvent", params, session_id=session_id
        )
        return

    if event in ("keydown", "keyup"):
        params = {
            "type": "keyDown" if event == "keydown" else "keyUp",
            "key": str(msg.get("key", "")),
            "code": str(msg.get("code", "")),
            "modifiers": int(msg.get("modifiers", 0) or 0),
        }
        vk = msg.get("windowsVirtualKeyCode")
        if vk is not None:
            params["windowsVirtualKeyCode"] = int(vk)
            params["nativeVirtualKeyCode"] = int(vk)
        text = msg.get("text")
        if text:
            params["text"] = str(text)
            params["unmodifiedText"] = str(text)
        await client.notify(
            "Input.dispatchKeyEvent", params, session_id=session_id
        )
        return

    if event == "keychar":
        text = str(msg.get("text", ""))
        if not text:
            return
        await client.notify(
            "Input.dispatchKeyEvent",
            {"type": "char", "text": text},
            session_id=session_id,
        )
        return

    if event == "insertText":
        text = str(msg.get("text", ""))
        if not text:
            return
        await client.notify(
            "Input.insertText", {"text": text}, session_id=session_id
        )
        return


async def dispatch_navigate(
    client: CdpBrowserClient, session_id: str, msg: dict
) -> None:
    action = msg.get("action")
    if action == "goto":
        url = str(msg.get("url", "")).strip()
        if not url:
            return
        if not url.startswith(("http://", "https://", "about:", "file://", "chrome://")):
            url = f"https://{url}"
        await client.notify("Page.navigate", {"url": url}, session_id=session_id)
        return

    if action == "reload":
        await client.notify(
            "Page.reload",
            {"ignoreCache": bool(msg.get("hard", False))},
            session_id=session_id,
        )
        return

    if action in ("back", "forward"):
        expr = "window.history.back()" if action == "back" else "window.history.forward()"
        await client.notify(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": False, "returnByValue": True},
            session_id=session_id,
        )
        return


# ---------- Screencast websocket ----------


DEFAULT_SCREENCAST_PARAMS: dict[str, Any] = {
    "format": "jpeg",
    "quality": 85,
    "maxWidth": 1920,
    "maxHeight": 1080,
    "everyNthFrame": 1,
}


def _sanitize_quality(msg: dict, current: dict[str, Any]) -> dict[str, Any]:
    """Merge user-supplied quality params on top of current, clamped to sane ranges."""
    out = dict(current)
    if "maxWidth" in msg:
        out["maxWidth"] = max(64, min(4096, int(msg["maxWidth"])))
    if "maxHeight" in msg:
        out["maxHeight"] = max(64, min(4096, int(msg["maxHeight"])))
    if "quality" in msg:
        out["quality"] = max(1, min(100, int(msg["quality"])))
    if "everyNthFrame" in msg:
        out["everyNthFrame"] = max(1, min(60, int(msg["everyNthFrame"])))
    return out


def _sanitize_viewport(msg: dict) -> dict[str, Any] | None:
    """Build an Emulation.setDeviceMetricsOverride params dict, or None if invalid."""
    try:
        width = int(msg.get("width", 0))
        height = int(msg.get("height", 0))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    width = max(64, min(4096, width))
    height = max(64, min(4096, height))
    scale = float(msg.get("deviceScaleFactor", 1) or 1)
    scale = max(0.1, min(4.0, scale))
    return {
        "width": width,
        "height": height,
        "deviceScaleFactor": scale,
        "mobile": bool(msg.get("mobile", False)),
    }


@router.websocket("/ws/browser/screencast")
async def browser_screencast(websocket: WebSocket) -> None:
    await websocket.accept()
    host, port = _chrome_endpoint(websocket)

    # Resolve initial target: explicit ?targetId=... wins, otherwise first page.
    initial_target_id = websocket.query_params.get("targetId")
    if not initial_target_id:
        try:
            targets = await _list_page_targets(host, port)
        except Exception as exc:
            logger.exception("failed to list page targets")
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close()
            return
        if not targets:
            await websocket.send_json({"type": "error", "message": "no page target found"})
            await websocket.close()
            return
        initial_target_id = targets[0]["id"]

    try:
        browser_ws_url = await _browser_ws_url(host, port)
    except Exception as exc:
        logger.exception("failed to resolve browser ws url")
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    try:
        async with websockets.connect(browser_ws_url, max_size=None) as cdp_ws:
            client = CdpBrowserClient(cdp_ws)

            # Mutable state: which target/session we are currently streaming,
            # plus sticky settings (re-applied on every target switch).
            state: dict[str, Any] = {
                "target_id": None,
                "session_id": None,
                "viewport": None,  # Emulation.setDeviceMetricsOverride params, or None
                "quality": dict(DEFAULT_SCREENCAST_PARAMS),
            }
            switch_lock = asyncio.Lock()

            async def on_event(msg: dict) -> None:
                method = msg.get("method")
                envelope_sid = msg.get("sessionId")
                params = msg.get("params", {}) or {}

                if method == "Page.screencastFrame":
                    # Drop frames from stale sessions (e.g. mid-switch).
                    if envelope_sid != state["session_id"]:
                        return
                    await websocket.send_json(
                        {
                            "type": "frame",
                            "targetId": state["target_id"],
                            "format": "jpeg",
                            "data": params["data"],
                            "metadata": params.get("metadata", {}),
                        }
                    )
                    with contextlib.suppress(Exception):
                        await client.notify(
                            "Page.screencastFrameAck",
                            {"sessionId": params["sessionId"]},
                            session_id=envelope_sid,
                        )
                    return

                if method in (
                    "Target.targetCreated",
                    "Target.targetInfoChanged",
                    "Target.targetDestroyed",
                ):
                    # Only signal — frontend re-fetches /browser/tabs.
                    info = params.get("targetInfo") or {}
                    is_page = info.get("type") == "page" or method == "Target.targetDestroyed"
                    if not is_page:
                        return
                    payload: dict[str, Any] = {"type": "tabs_changed"}
                    if method == "Target.targetDestroyed":
                        destroyed = params.get("targetId")
                        payload["destroyed"] = destroyed
                        if destroyed == state["target_id"]:
                            payload["currentClosed"] = True
                    with contextlib.suppress(Exception):
                        await websocket.send_json(payload)
                    return

            client.event_handler = on_event

            async def attach_and_start(target_id: str) -> None:
                async with switch_lock:
                    old_sid = state["session_id"]
                    # Optimistically clear so frames from old session get dropped.
                    state["session_id"] = None
                    state["target_id"] = None

                    if old_sid is not None:
                        with contextlib.suppress(Exception):
                            await client.call(
                                "Page.stopScreencast", session_id=old_sid
                            )
                        with contextlib.suppress(Exception):
                            await client.call(
                                "Target.detachFromTarget",
                                {"sessionId": old_sid},
                            )

                    attach_res = await client.call(
                        "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True},
                    )
                    new_sid = attach_res.get("sessionId")
                    if not new_sid:
                        raise RuntimeError("attachToTarget returned no sessionId")

                    await client.call("Page.enable", session_id=new_sid)
                    await client.call(
                        "Input.setIgnoreInputEvents",
                        {"ignore": False},
                        session_id=new_sid,
                    )
                    # Re-apply sticky viewport override (lost on detach).
                    if state["viewport"]:
                        with contextlib.suppress(Exception):
                            await client.call(
                                "Emulation.setDeviceMetricsOverride",
                                state["viewport"],
                                session_id=new_sid,
                            )
                    state["session_id"] = new_sid
                    state["target_id"] = target_id
                    await client.call(
                        "Page.startScreencast",
                        state["quality"],
                        session_id=new_sid,
                    )
                    with contextlib.suppress(Exception):
                        await client.call(
                            "Target.activateTarget", {"targetId": target_id}
                        )
                    with contextlib.suppress(Exception):
                        await websocket.send_json(
                            {"type": "target_switched", "targetId": target_id}
                        )

            # Pump must run before any call() — responses come through it.
            pump_task = asyncio.create_task(client.pump())

            # Subscribe to target lifecycle events so we can notify the frontend.
            with contextlib.suppress(Exception):
                await client.call(
                    "Target.setDiscoverTargets", {"discover": True}
                )

            try:
                await attach_and_start(initial_target_id)
            except Exception as exc:
                logger.exception("initial attach failed")
                with contextlib.suppress(Exception):
                    await websocket.send_json(
                        {"type": "error", "message": str(exc)}
                    )
                pump_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pump_task
                return

            async def apply_viewport(viewport: dict | None) -> None:
                """Persist viewport setting + apply to current session if any."""
                state["viewport"] = viewport
                sid = state["session_id"]
                if not sid:
                    return
                if viewport is None:
                    with contextlib.suppress(Exception):
                        await client.call(
                            "Emulation.clearDeviceMetricsOverride",
                            session_id=sid,
                        )
                else:
                    with contextlib.suppress(Exception):
                        await client.call(
                            "Emulation.setDeviceMetricsOverride",
                            viewport,
                            session_id=sid,
                        )
                with contextlib.suppress(Exception):
                    await websocket.send_json(
                        {"type": "viewport_changed", "viewport": viewport}
                    )

            async def apply_quality(new_quality: dict) -> None:
                """Persist quality + restart screencast on current session."""
                state["quality"] = new_quality
                sid = state["session_id"]
                if not sid:
                    return
                async with switch_lock:
                    sid = state["session_id"]
                    if not sid:
                        return
                    with contextlib.suppress(Exception):
                        await client.call("Page.stopScreencast", session_id=sid)
                    with contextlib.suppress(Exception):
                        await client.call(
                            "Page.startScreencast",
                            new_quality,
                            session_id=sid,
                        )
                with contextlib.suppress(Exception):
                    await websocket.send_json(
                        {"type": "quality_changed", "quality": new_quality}
                    )

            async def receive_input() -> None:
                while True:
                    msg = await websocket.receive_json()
                    if not isinstance(msg, dict):
                        continue
                    msg_type = msg.get("type")
                    try:
                        if msg_type == "input":
                            sid = state["session_id"]
                            if sid:
                                await dispatch_input(client, sid, msg)
                        elif msg_type == "navigate":
                            sid = state["session_id"]
                            if sid:
                                await dispatch_navigate(client, sid, msg)
                        elif msg_type == "switch_target":
                            new_target = str(msg.get("targetId", "")).strip()
                            if new_target and new_target != state["target_id"]:
                                await attach_and_start(new_target)
                        elif msg_type == "set_viewport":
                            viewport = _sanitize_viewport(msg)
                            if viewport is not None:
                                await apply_viewport(viewport)
                        elif msg_type == "reset_viewport":
                            await apply_viewport(None)
                        elif msg_type == "set_quality":
                            new_q = _sanitize_quality(msg, state["quality"])
                            await apply_quality(new_q)
                    except Exception:
                        logger.exception("dispatch failed: %s", msg)

            input_task = asyncio.create_task(receive_input())
            done, pending = await asyncio.wait(
                {pump_task, input_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            for task in done:
                exc = task.exception()
                if exc and not isinstance(
                    exc, (WebSocketDisconnect, asyncio.CancelledError)
                ):
                    logger.exception("screencast task failed", exc_info=exc)
    except WebSocketDisconnect:
        logger.info("frontend disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("screencast loop crashed")
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()
