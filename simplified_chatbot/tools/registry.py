"""Nanobot-style tool registry for simplified_chatbot."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from simplified_chatbot.tools.base import Tool


class ToolRegistry:
    """Registry for tools, schemas, validation, and execution."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._cached_definitions: list[dict[str, Any]] | None = None

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        self._cached_definitions = None

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._cached_definitions = None

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        return name in self._tools

    @staticmethod
    def _schema_name(schema: dict[str, Any]) -> str:
        function = schema.get("function")
        if isinstance(function, dict):
            name = function.get("name")
            if isinstance(name, str):
                return name
        name = schema.get("name")
        return name if isinstance(name, str) else ""

    def get_definitions(self) -> list[dict[str, Any]]:
        if self._cached_definitions is not None:
            return self._cached_definitions

        definitions = [tool.to_schema() for tool in self._tools.values()]
        builtins: list[dict[str, Any]] = []
        mcp_tools: list[dict[str, Any]] = []
        for schema in definitions:
            name = self._schema_name(schema)
            if name.startswith("mcp_"):
                mcp_tools.append(schema)
            else:
                builtins.append(schema)

        builtins.sort(key=self._schema_name)
        mcp_tools.sort(key=self._schema_name)
        self._cached_definitions = builtins + mcp_tools
        return self._cached_definitions

    def prepare_call(
        self,
        name: str,
        params: dict[str, Any],
    ) -> tuple[Tool | None, dict[str, Any], str | None]:
        tool = self._tools.get(name)
        if tool is None:
            return None, params, (
                f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"
            )

        cast_params = tool.cast_params(params)
        errors = tool.validate_params(cast_params)
        if errors:
            return tool, cast_params, (
                f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors)
            )
        return tool, cast_params, None

    def execute(
        self,
        name: str,
        params: dict[str, Any],
    ) -> Any:
        """Execute one tool synchronously in the current simplified runtime."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, cast_params, error = self.prepare_call(name, params)
        if error:
            return error + hint

        try:
            assert tool is not None
            result = _run_tool(tool.execute(**cast_params))
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as exc:
            return f"Error executing {name}: {exc}" + hint

    async def execute_async(
        self,
        name: str,
        params: dict[str, Any],
    ) -> Any:
        """Execute one tool from an async runtime."""
        hint = "\n\n[Analyze the error above and try a different approach.]"
        tool, cast_params, error = self.prepare_call(name, params)
        if error:
            return error + hint

        try:
            assert tool is not None
            result = tool.execute(**cast_params)
            if asyncio.iscoroutine(result):
                result = await result
            if isinstance(result, str) and result.startswith("Error"):
                return result + hint
            return result
        except Exception as exc:
            return f"Error executing {name}: {exc}" + hint

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def _run_tool(awaitable: Any) -> Any:
    """Run an async tool method from the current sync runtime."""
    if not asyncio.iscoroutine(awaitable):
        return awaitable
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _DEFAULT_ASYNC_TOOL_RUNNER.run(awaitable)
    raise RuntimeError(
        "Cannot execute async tools from a running event loop in the current sync runtime",
    )


class _AsyncToolRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def run(self, coro: Any) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            self._thread = threading.Thread(
                target=self._thread_main,
                name="simplified-chatbot-async-tools",
                daemon=True,
            )
            self._thread.start()
        self._ready.wait()
        assert self._loop is not None
        return self._loop

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()


_DEFAULT_ASYNC_TOOL_RUNNER = _AsyncToolRunner()
