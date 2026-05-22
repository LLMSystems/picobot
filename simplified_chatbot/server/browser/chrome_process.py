import asyncio
import contextlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger("screencast.chrome")


def _find_chrome_bin() -> str:
    browsers_dir = Path.home() / ".agent-browser" / "browsers"
    if browsers_dir.is_dir():
        candidates = sorted(browsers_dir.glob("chrome-*/chrome"), reverse=True)
        if candidates:
            return str(candidates[0])
    return "google-chrome"


CHROME_BIN = _find_chrome_bin()
CDP_PORT = 9222
CDP_HOST = "0.0.0.0"


class ChromeProcess:
    def __init__(self, binary: str = CHROME_BIN, port: int = CDP_PORT, host: str = CDP_HOST):
        self.binary = binary
        self.port = port
        self.host = host
        self.proc: subprocess.Popen | None = None
        self.user_data_dir: str | None = None
        self._pgid: int | None = None

    def _kill_port_squatters(self) -> None:
        result = subprocess.run(
            ["ss", "-tlnpH", f"sport = :{self.port}"],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            for part in line.split(","):
                if part.startswith("pid="):
                    try:
                        pid = int(part.split("=")[1])
                        logger.warning("killing stale process on port %s: pid=%s", self.port, pid)
                        with contextlib.suppress(ProcessLookupError, PermissionError):
                            os.kill(pid, signal.SIGKILL)
                    except ValueError:
                        pass

    async def start(self) -> None:
        self._kill_port_squatters()
        self.user_data_dir = tempfile.mkdtemp(prefix="ai-browser-profile-")
        args = [
            self.binary,
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=960,1080",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "https://www.google.com.tw/index.html",
        ]
        logger.info("starting chrome: %s", " ".join(args))
        env = {**os.environ, "DISPLAY": ":99"}
        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
        # store pgid immediately — headless launcher exits quickly, pid becomes unavailable later
        self._pgid = os.getpgid(self.proc.pid)
        await self._wait_until_ready()

    async def _wait_until_ready(self, timeout: float = 15.0) -> None:
        deadline = asyncio.get_event_loop().time() + timeout
        url = f"http://{self.host}:{self.port}/json/version"
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    resp = await client.get(url, timeout=1.0)
                    if resp.status_code == 200:
                        logger.info("chrome ready on port %s", self.port)
                        return
                except (httpx.ConnectError, httpx.ReadTimeout):
                    pass
                if asyncio.get_event_loop().time() > deadline:
                    raise RuntimeError("chrome did not become ready in time")
                await asyncio.sleep(0.2)

    def stop(self) -> None:
        pgid = self._pgid
        if pgid is None:
            return
        logger.info("stopping chrome pgid=%s", pgid)
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(pgid, signal.SIGTERM)
        if self.proc:
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(pgid, signal.SIGKILL)
        self._pgid = None
        if self.user_data_dir and os.path.isdir(self.user_data_dir):
            shutil.rmtree(self.user_data_dir, ignore_errors=True)
