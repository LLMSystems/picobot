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

    async def send_command(self, method: str, params: dict | None = None) -> int:
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
    except WebSocketDisconnect:
        logger.info("frontend disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("screencast loop crashed")
    finally:
        with contextlib.suppress(RuntimeError):
            await websocket.close()

