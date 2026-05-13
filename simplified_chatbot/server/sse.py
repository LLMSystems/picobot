"""Helpers for encoding Server-Sent Events."""

from __future__ import annotations

import json
from typing import Any


def encode_sse(*, event: str, data: Any) -> bytes:
    """Encode one SSE event frame."""
    if isinstance(data, str):
        payload = data
    else:
        payload = json.dumps(data, ensure_ascii=False)

    lines = [f"event: {event}"]
    for line in payload.split("\n"):
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines).encode("utf-8")
