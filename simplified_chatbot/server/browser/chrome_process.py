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

    def _pids_on_port(self) -> list[int]:
        """Return PIDs listening on self.port by reading /proc/net/tcp."""
        hex_port = f"{self.port:04X}"
        pids: list[int] = []
        try:
            with open("/proc/net/tcp") as f:
                inodes = {
                    line.split()[9]
                    for line in f.read().splitlines()[1:]
                    if line.split()[1].endswith(f":{hex_port}") and line.split()[3] == "0A"
                }
        except OSError:
            return pids
        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            fd_dir = proc_dir / "fd"
            try:
                for fd in fd_dir.iterdir():
                    target = os.readlink(fd)
                    # socket:[inode]
                    if target.startswith("socket:[") and target[8:-1] in inodes:
                        pids.append(int(proc_dir.name))
                        break
            except (OSError, PermissionError):
                pass
        return pids

    def _kill_port_squatters(self) -> None:
        for pid in self._pids_on_port():
            logger.warning("killing stale process on port %s: pid=%s", self.port, pid)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)

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
