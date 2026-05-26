import json
import logging
from typing import Any
import asyncio
import contextlib

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request


logger = logging.getLogger("screencast.router")


class CdpConnection:
    def __init__(self, ws: Any):
        self.ws = ws
        self.next_id = 1
        self._lock = asyncio.Lock()

    async def send_command(self, method: str, params: dict | None = None) -> int:
        async with self._lock:
            command_id = self.next_id
            self.next_id += 1
            payload: dict[str, Any] = {"id": command_id, "method": method}
            if params is not None:
                payload["params"] = params
            await self.ws.send(json.dumps(payload))
            return command_id


router = APIRouter()

@router.get("/health/chrome")
async def health(request: Request) -> dict[str, Any]:
    chrome = request.app.state.chrome
    alive = chrome is not None and chrome.proc is not None and chrome.proc.poll() is None
    return {"chrome_alive": alive, "cdp_port": chrome.port}

async def get_page_websocket_url(host, port) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://{host}:{port}/json")
        resp.raise_for_status()
        targets = resp.json()
    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return target["webSocketDebuggerUrl"]
    raise RuntimeError("no page target found")


MOUSE_EVENT_TYPE_MAP = {
    "mousedown": "mousePressed",
    "mouseup": "mouseReleased",
    "mousemove": "mouseMoved",
    "wheel": "mouseWheel",
}

ALLOWED_MOUSE_BUTTONS = {"left", "middle", "right", "none"}


async def dispatch_input(cdp: CdpConnection, msg: dict) -> None:
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
        await cdp.send_command("Input.dispatchMouseEvent", params)
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
        await cdp.send_command("Input.dispatchKeyEvent", params)
        return

    if event == "keychar":
        text = str(msg.get("text", ""))
        if not text:
            return
        await cdp.send_command(
            "Input.dispatchKeyEvent",
            {"type": "char", "text": text},
        )
        return

    if event == "insertText":
        text = str(msg.get("text", ""))
        if not text:
            return
        await cdp.send_command("Input.insertText", {"text": text})
        return


async def dispatch_navigate(cdp: CdpConnection, msg: dict) -> None:
    action = msg.get("action")
    if action == "goto":
        url = str(msg.get("url", "")).strip()
        if not url:
            return
        if not url.startswith(("http://", "https://", "about:", "file://", "chrome://")):
            url = f"https://{url}"
        await cdp.send_command("Page.navigate", {"url": url})
        return

    if action == "reload":
        await cdp.send_command("Page.reload", {"ignoreCache": bool(msg.get("hard", False))})
        return

    if action in ("back", "forward"):
        # window.history shim — simpler than Page.getNavigationHistory + navigateToHistoryEntry
        expr = "window.history.back()" if action == "back" else "window.history.forward()"
        await cdp.send_command(
            "Runtime.evaluate",
            {"expression": expr, "awaitPromise": False, "returnByValue": True},
        )
        return


@router.websocket("/ws/browser/screencast")
async def browser_screencast(websocket: WebSocket) -> None:
    await websocket.accept()
    config = websocket.app.state.config
    host = config.browser.get("host", "localhost") if config.browser else "localhost"
    port = config.browser.get("chromeDebuggingPort", 9222) if config.browser else 9222

    try:
        cdp_ws_url = await get_page_websocket_url(host, port)
    except Exception as exc:
        logger.exception("failed to find page target")
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    try:
        async with websockets.connect(cdp_ws_url, max_size=None) as cdp_ws:
            cdp = CdpConnection(cdp_ws)
            await cdp.send_command("Page.enable")
            await cdp.send_command("Input.setIgnoreInputEvents", {"ignore": False})
            await cdp.send_command(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 85,
                    "maxWidth": 1920,
                    "maxHeight": 1080,
                    "everyNthFrame": 1,
                },
            )

            async def forward_frames() -> None:
                async for raw in cdp_ws:
                    event = json.loads(raw)
                    if event.get("method") != "Page.screencastFrame":
                        continue
                    params = event["params"]
                    session_id = params["sessionId"]
                    await websocket.send_json(
                        {
                            "type": "frame",
                            "format": "jpeg",
                            "data": params["data"],
                            "metadata": params.get("metadata", {}),
                        }
                    )
                    await cdp.send_command(
                        "Page.screencastFrameAck",
                        {"sessionId": session_id},
                    )

            async def receive_input() -> None:
                while True:
                    msg = await websocket.receive_json()
                    if not isinstance(msg, dict):
                        continue
                    msg_type = msg.get("type")
                    try:
                        if msg_type == "input":
                            await dispatch_input(cdp, msg)
                        elif msg_type == "navigate":
                            await dispatch_navigate(cdp, msg)
                    except Exception:
                        logger.exception("dispatch failed: %s", msg)

            frames_task = asyncio.create_task(forward_frames())
            input_task = asyncio.create_task(receive_input())
            done, pending = await asyncio.wait(
                {frames_task, input_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
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
