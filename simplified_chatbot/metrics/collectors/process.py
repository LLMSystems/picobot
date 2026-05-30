"""Process-level resource samples (CPU, RSS, threads)."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import psutil  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - psutil ships in pyproject
    psutil = None  # type: ignore[assignment]


@dataclass
class ProcessSample:
    cpu_percent: float | None
    rss_bytes: int | None
    threads: int | None


class ProcessCollector:
    """Sample current-process CPU and memory via psutil."""

    def __init__(self) -> None:
        if psutil is None:
            self._process = None
        else:
            self._process = psutil.Process(os.getpid())
            # Prime cpu_percent so the first real call returns a non-zero delta.
            try:
                self._process.cpu_percent(interval=None)
            except Exception:
                pass

    def collect(self) -> ProcessSample:
        if self._process is None:
            return ProcessSample(cpu_percent=None, rss_bytes=None, threads=None)
        try:
            cpu = float(self._process.cpu_percent(interval=None))
            mem = int(self._process.memory_info().rss)
            threads = int(self._process.num_threads())
            return ProcessSample(cpu_percent=cpu, rss_bytes=mem, threads=threads)
        except Exception:
            return ProcessSample(cpu_percent=None, rss_bytes=None, threads=None)
