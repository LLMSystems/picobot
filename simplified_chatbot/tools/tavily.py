"""Tavily web search tool for current-information lookups."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from simplified_chatbot.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query or question to look up on the web.",
                "minLength": 1,
            },
            "topic": {
                "type": "string",
                "description": "Search topic. Use 'news' for recent events or 'finance' for market data.",
                "enum": ["general", "news", "finance"],
            },
            "search_depth": {
                "type": "string",
                "description": "Search depth. 'basic' is a good default; 'advanced' is slower and richer.",
                "enum": ["basic", "advanced", "fast", "ultra-fast"],
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of search results to return.",
                "minimum": 1,
                "maximum": 20,
            },
            "time_range": {
                "type": "string",
                "description": "Optional recency filter. Useful with topic='news'.",
                "enum": ["day", "week", "month", "year", "d", "w", "m", "y"],
            },
            "include_answer": {
                "type": "string",
                "description": "Whether Tavily should synthesize an answer.",
                "enum": ["false", "basic", "advanced"],
            },
            "include_raw_content": {
                "type": "string",
                "description": "Whether to include cleaned page content in results.",
                "enum": ["false", "markdown", "text"],
            },
            "include_domains": {
                "type": "array",
                "description": "Optional allowlist of domains to search.",
                "items": {"type": "string"},
                "maxItems": 100,
            },
            "exclude_domains": {
                "type": "array",
                "description": "Optional denylist of domains to exclude.",
                "items": {"type": "string"},
                "maxItems": 50,
            },
        },
        "required": ["query"],
    },
)
class TavilySearchTool(Tool):
    """Search the public web using Tavily and return a normalized result."""

    _DEFAULT_BASE_URL = "https://api.tavily.com"
    _DEFAULT_TIMEOUT = 30
    _MAX_SNIPPET_CHARS = 1200
    read_only = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._api_base = (api_base or self._DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "tavily_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for up-to-date information using Tavily. "
            "Returns a normalized JSON object with query, answer, top results, usage, and request_id."
        )

    async def execute(
        self,
        query: str,
        topic: str = "general",
        search_depth: str = "basic",
        max_results: int = 5,
        time_range: str | None = None,
        include_answer: str = "false",
        include_raw_content: str = "false",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | str:
        query_text = query.strip()
        if not query_text:
            return "Error: query must not be empty"

        api_key = self._api_key or os.environ.get("TAVILY_API_KEY")
        if not api_key:
            return "Error: TAVILY_API_KEY is not set"

        payload: dict[str, Any] = {
            "query": query_text,
            "topic": topic,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_usage": True,
        }
        if time_range:
            payload["time_range"] = time_range
        if include_answer != "false":
            payload["include_answer"] = include_answer
        if include_raw_content != "false":
            payload["include_raw_content"] = include_raw_content
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains

        try:
            response = await self._post_search(payload, api_key)
        except Exception as exc:
            return f"Error: Tavily search failed: {exc}"
        return self._normalize_response(response)

    async def _post_search(
        self,
        payload: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._post_search_sync, payload, api_key)

    def _post_search_sync(
        self,
        payload: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self._api_base}/search",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"HTTP {exc.code} from Tavily: {detail or exc.reason}",
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"Could not reach Tavily: {exc.reason}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Tavily returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Tavily returned a non-object response")
        return parsed

    def _normalize_response(self, response: dict[str, Any]) -> dict[str, Any]:
        normalized_results: list[dict[str, Any]] = []
        for item in response.get("results", []) or []:
            if not isinstance(item, dict):
                continue
            entry: dict[str, Any] = {
                "title": str(item.get("title", "")),
                "url": str(item.get("url", "")),
                "content": self._trim_text(item.get("content")),
            }
            raw_content = item.get("raw_content")
            if raw_content not in {None, ""}:
                entry["raw_content"] = self._trim_text(raw_content)
            score = item.get("score")
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                entry["score"] = score
            normalized_results.append(entry)

        normalized: dict[str, Any] = {
            "query": str(response.get("query", "")),
            "results": normalized_results,
            "request_id": response.get("request_id"),
        }
        answer = response.get("answer")
        if answer not in {None, ""}:
            normalized["answer"] = self._trim_text(answer)
        usage = response.get("usage")
        if isinstance(usage, dict):
            normalized["usage"] = usage
        response_time = response.get("response_time")
        if isinstance(response_time, (int, float)) and not isinstance(response_time, bool):
            normalized["response_time"] = response_time
        return normalized

    def _trim_text(self, value: Any) -> str:
        text = str(value or "")
        if len(text) <= self._MAX_SNIPPET_CHARS:
            return text
        return text[: self._MAX_SNIPPET_CHARS] + "... [truncated]"

