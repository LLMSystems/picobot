"""Web fetch tool: retrieve a single URL and return readable text."""

from __future__ import annotations

import asyncio
import re
from html.parser import HTMLParser
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from simplified_chatbot.tools.base import Tool, tool_parameters

_DEFAULT_MAX_CHARS = 50_000
_DEFAULT_TIMEOUT = 30
_DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Picobot/1.0; +https://github.com/)"
_SKIP_TAGS = frozenset({"script", "style", "noscript", "template"})
_BLOCK_TAGS = frozenset(
    {
        "p", "div", "section", "article", "header", "footer", "main",
        "aside", "nav", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "br", "hr", "blockquote", "pre",
    },
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        joined = "".join(self._chunks)
        collapsed = re.sub(r"[ \t]+", " ", joined)
        collapsed = re.sub(r"\n[ \t]+", "\n", collapsed)
        collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
        return collapsed.strip()


def _looks_like_html(content_type: str, body: str) -> bool:
    if "html" in content_type.lower():
        return True
    snippet = body[:1024].lstrip().lower()
    return snippet.startswith("<!doctype html") or snippet.startswith("<html")


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n... [truncated]", True


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP or HTTPS URL to fetch.",
                "minLength": 1,
            },
            "format": {
                "type": "string",
                "enum": ["text", "raw"],
                "description": (
                    "How to return the body. 'text' strips HTML tags and returns readable text; "
                    "'raw' returns the response body unchanged. Default 'text'."
                ),
            },
            "max_chars": {
                "type": "integer",
                "description": "Truncate the returned body to this many characters (default 50000).",
                "minimum": 1000,
                "maximum": 500_000,
            },
            "timeout": {
                "type": "integer",
                "description": "Request timeout in seconds (default 30).",
                "minimum": 1,
                "maximum": 120,
            },
        },
        "required": ["url"],
    },
)
class WebFetchTool(Tool):
    """Fetch a single URL and return readable text or raw body."""

    def __init__(self, *, user_agent: str | None = None) -> None:
        self._user_agent = user_agent or _DEFAULT_USER_AGENT

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch the content of a single HTTP/HTTPS URL. "
            "Default 'text' mode strips HTML tags and returns readable text; "
            "use 'raw' mode for JSON, plain text, or when you need the original body. "
            "Use this when you have a specific URL; use tavily_search to discover URLs."
        )

    async def execute(
        self,
        url: str | None = None,
        format: str = "text",
        max_chars: int = _DEFAULT_MAX_CHARS,
        timeout: int = _DEFAULT_TIMEOUT,
        **kwargs: Any,
    ) -> dict[str, Any] | str:
        if not url or not url.strip():
            return "Error: url must not be empty"
        if format not in {"text", "raw"}:
            return "Error: format must be 'text' or 'raw'"

        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            return f"Error: only http and https URLs are supported (got scheme '{parsed.scheme}')"
        if not parsed.netloc:
            return "Error: url is missing a host"

        try:
            status, content_type, body = await asyncio.to_thread(
                self._fetch_sync, url.strip(), timeout,
            )
        except Exception as exc:
            return f"Error: web_fetch failed: {exc}"

        is_html = _looks_like_html(content_type, body)
        if format == "text" and is_html:
            extractor = _TextExtractor()
            try:
                extractor.feed(body)
                extractor.close()
                content = extractor.get_text()
            except Exception:
                content = body
        else:
            content = body

        content, truncated = _truncate(content, max_chars)

        return {
            "url": url.strip(),
            "status": status,
            "content_type": content_type,
            "format": format,
            "truncated": truncated,
            "content": content,
        }

    def _fetch_sync(self, url: str, timeout: int) -> tuple[int, str, str]:
        req = request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {exc.code} from {url}: {detail[:500] or exc.reason}",
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc

        charset = "utf-8"
        if "charset=" in content_type.lower():
            charset = content_type.lower().split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            body = raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            body = raw.decode("utf-8", errors="replace")
        return status, content_type, body
