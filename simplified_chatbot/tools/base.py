"""Nanobot-aligned tool base classes for simplified_chatbot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from copy import deepcopy
from typing import Any, TypeVar

_ToolT = TypeVar("_ToolT", bound="Tool")

_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class Schema:
    """Shared JSON schema validation helpers."""

    @staticmethod
    def resolve_json_schema_type(value: Any) -> str | None:
        if isinstance(value, list):
            return next((item for item in value if item != "null"), None)
        return value

    @staticmethod
    def subpath(path: str, key: str) -> str:
        return f"{path}.{key}" if path else key

    @staticmethod
    def validate_json_schema_value(
        value: Any,
        schema: dict[str, Any],
        path: str = "",
    ) -> list[str]:
        raw_type = schema.get("type")
        nullable = (
            isinstance(raw_type, list) and "null" in raw_type
        ) or schema.get("nullable", False)
        resolved_type = Schema.resolve_json_schema_type(raw_type)
        label = path or "parameter"

        if nullable and value is None:
            return []
        if resolved_type == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return [f"{label} should be integer"]
        if resolved_type == "number" and (
            not isinstance(value, _JSON_TYPE_MAP["number"]) or isinstance(value, bool)
        ):
            return [f"{label} should be number"]
        if (
            resolved_type in _JSON_TYPE_MAP
            and resolved_type not in {"integer", "number"}
            and not isinstance(value, _JSON_TYPE_MAP[resolved_type])
        ):
            return [f"{label} should be {resolved_type}"]

        errors: list[str] = []
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")
        if resolved_type in {"integer", "number"}:
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")
        if resolved_type == "string":
            if "minLength" in schema and len(value) < schema["minLength"]:
                errors.append(
                    f"{label} must be at least {schema['minLength']} chars",
                )
            if "maxLength" in schema and len(value) > schema["maxLength"]:
                errors.append(
                    f"{label} must be at most {schema['maxLength']} chars",
                )
        if resolved_type == "object":
            properties = schema.get("properties", {})
            for key in schema.get("required", []):
                if key not in value:
                    errors.append(f"missing required {Schema.subpath(path, key)}")
            for key, item in value.items():
                if key in properties:
                    errors.extend(
                        Schema.validate_json_schema_value(
                            item,
                            properties[key],
                            Schema.subpath(path, key),
                        ),
                    )
        if resolved_type == "array":
            if "minItems" in schema and len(value) < schema["minItems"]:
                errors.append(f"{label} must have at least {schema['minItems']} items")
            if "maxItems" in schema and len(value) > schema["maxItems"]:
                errors.append(f"{label} must be at most {schema['maxItems']} items")
            if "items" in schema:
                prefix = f"{path}[{{}}]" if path else "[{}]"
                for index, item in enumerate(value):
                    errors.extend(
                        Schema.validate_json_schema_value(
                            item,
                            schema["items"],
                            prefix.format(index),
                        ),
                    )
        return errors


class Tool(ABC):
    """Base interface aligned with nanobot's tool shape."""

    _TYPE_MAP = _JSON_TYPE_MAP
    _BOOL_TRUE = frozenset(("true", "1", "yes"))
    _BOOL_FALSE = frozenset(("false", "0", "no"))
    read_only = False
    exclusive = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON schema for tool parameters."""

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Run the tool."""

    @property
    def concurrency_safe(self) -> bool:
        """Whether this tool is safe to run alongside adjacent tool calls."""
        return self.read_only and not self.exclusive

    @classmethod
    def _resolve_type(cls, value: Any) -> str | None:
        return Schema.resolve_json_schema_type(value)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(obj, dict):
            return obj
        properties = schema.get("properties", {})
        return {
            key: self._cast_value(item, properties[key]) if key in properties else item
            for key, item in obj.items()
        }

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Apply schema-driven casts before validation."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            return params
        return self._cast_object(params, schema)

    def _cast_value(self, value: Any, schema: dict[str, Any]) -> Any:
        resolved_type = self._resolve_type(schema.get("type"))

        if resolved_type == "boolean" and isinstance(value, bool):
            return value
        if resolved_type == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return value
        if resolved_type in self._TYPE_MAP and resolved_type not in {
            "boolean",
            "integer",
            "array",
            "object",
        }:
            expected = self._TYPE_MAP[resolved_type]
            if isinstance(value, expected):
                return value

        if isinstance(value, str) and resolved_type in {"integer", "number"}:
            try:
                return int(value) if resolved_type == "integer" else float(value)
            except ValueError:
                return value

        if resolved_type == "string":
            return value if value is None else str(value)

        if resolved_type == "boolean" and isinstance(value, str):
            lowered = value.lower()
            if lowered in self._BOOL_TRUE:
                return True
            if lowered in self._BOOL_FALSE:
                return False
            return value

        if resolved_type == "array" and isinstance(value, list):
            items = schema.get("items")
            return [self._cast_value(item, items) for item in value] if items else value

        if resolved_type == "object" and isinstance(value, dict):
            return self._cast_object(value, schema)

        return value

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate parameters against the JSON schema."""
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return Schema.validate_json_schema_value(params, {**schema, "type": "object"})

    def to_schema(self) -> dict[str, Any]:
        """OpenAI-compatible function schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def tool_parameters(schema: dict[str, Any]) -> Callable[[type[_ToolT]], type[_ToolT]]:
    """Attach a stable parameters property to a Tool subclass."""

    def decorator(cls: type[_ToolT]) -> type[_ToolT]:
        frozen = deepcopy(schema)

        @property
        def parameters(self: Any) -> dict[str, Any]:
            return deepcopy(frozen)

        cls.parameters = parameters  # type: ignore[assignment]
        abstract = getattr(cls, "__abstractmethods__", None)
        if abstract is not None and "parameters" in abstract:
            cls.__abstractmethods__ = frozenset(abstract - {"parameters"})  # type: ignore[misc]
        return cls

    return decorator
