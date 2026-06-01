"""Fake tools for exercising the tool-calling loop."""

from __future__ import annotations

import ast
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.registry import ToolRegistry

_ARITHMETIC_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Constant,
)


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to echo back.",
            },
        },
        "required": ["text"],
    },
)
class EchoTool(Tool):
    read_only = True

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the provided text back exactly."

    async def execute(self, **kwargs: Any) -> Any:
        return str(kwargs["text"])


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name to look up in the fake weather table.",
            },
        },
        "required": ["city"],
    },
)
class GetWeatherTool(Tool):
    _WEATHER = {
        "taipei": "Taipei: cloudy, 28C",
        "tokyo": "Tokyo: sunny, 24C",
        "new york": "New York: rainy, 19C",
    }
    read_only = True

    @property
    def name(self) -> str:
        return "get_weather"

    @property
    def description(self) -> str:
        return "Return fake weather information for a city."

    async def execute(self, **kwargs: Any) -> Any:
        city = str(kwargs["city"]).strip()
        return self._WEATHER.get(city.lower(), f"{city}: weather data unavailable")


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression using numbers and operators.",
            },
        },
        "required": ["expression"],
    },
)
class CalculatorTool(Tool):
    read_only = True

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "Evaluate a basic arithmetic expression."

    async def execute(self, **kwargs: Any) -> Any:
        expression = str(kwargs["expression"]).strip()
        try:
            result = _evaluate_expression(expression)
        except Exception as exc:
            return f"Error: invalid expression ({exc})"
        return str(result)


def build_fake_tool_registry() -> ToolRegistry:
    """Create a registry preloaded with the fake demo tools."""
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(EchoTool())
    registry.register(GetWeatherTool())
    return registry


def _evaluate_expression(expression: str) -> int | float:
    tree = ast.parse(expression, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ARITHMETIC_NODES):
            raise ValueError(f"unsupported node: {type(node).__name__}")
    value = eval(compile(tree, "<calculator>", "eval"), {"__builtins__": {}}, {})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    raise ValueError("expression did not produce a numeric result")
