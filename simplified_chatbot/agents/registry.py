"""Load and resolve agent type definitions from a YAML manifest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_NAME_RE = re.compile(r"^[a-z0-9_-]+$")

# Canonical set of builtin tool names registrable under the "main" profile.
# An agent type's `tools` allowlist is validated against this set so typos fail
# fast. A test asserts this stays in sync with the actual main-profile registry.
KNOWN_TOOL_NAMES = frozenset(
    {
        "exec",
        "write_stdin",
        "list_exec_sessions",
        "tavily_search",
        "web_fetch",
        "read_file",
        "view_image",
        "write_file",
        "edit_file",
        "apply_patch",
        "list_dir",
        "glob",
        "grep",
        "todo_write",
        "ask_user_question",
        "spawn",
        "list_subagents",
        "subagent_wait",
        "cancel_subagent",
    },
)


@dataclass(frozen=True)
class AgentDefinition:
    """One agent type: a base prompt plus an optional tool allowlist."""

    name: str
    display_name: str
    description: str
    prompt_file: Path
    tools: tuple[str, ...] | None  # None means "all tools" ("*")

    def load_prompt(self) -> str:
        """Read this agent type's base system prompt."""
        return self.prompt_file.read_text(encoding="utf-8").strip()


class AgentRegistry:
    """Resolve agent types declared in a YAML manifest."""

    def __init__(
        self,
        definitions: dict[str, AgentDefinition],
        default_name: str,
    ) -> None:
        self._definitions = definitions
        self._default_name = default_name

    @classmethod
    def builtin_path(cls) -> Path:
        """Path to the packaged registry manifest."""
        return Path(__file__).with_name("registry.yaml")

    @classmethod
    def load(cls, path: str | Path | None = None) -> "AgentRegistry":
        """Load the registry from a manifest, or fall back to a single default."""
        manifest_path = Path(path).expanduser() if path is not None else cls.builtin_path()
        if not manifest_path.exists():
            return cls._fallback()

        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"Agent registry must be a mapping: {manifest_path}")

        base_dir = manifest_path.resolve().parent
        entries = raw.get("agents") or []
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"Agent registry must declare a non-empty 'agents' list: {manifest_path}")

        definitions: dict[str, AgentDefinition] = {}
        for entry in entries:
            definition = cls._parse_entry(entry, base_dir=base_dir, manifest_path=manifest_path)
            if definition.name in definitions:
                raise ValueError(f"Duplicate agent type name '{definition.name}' in {manifest_path}")
            definitions[definition.name] = definition

        default_name = raw.get("default") or next(iter(definitions))
        if default_name not in definitions:
            raise ValueError(
                f"Agent registry 'default' points to unknown type '{default_name}' in {manifest_path}",
            )
        return cls(definitions, default_name)

    @classmethod
    def _fallback(cls) -> "AgentRegistry":
        """Single built-in default type pointing at the legacy system prompt."""
        prompt_file = Path(__file__).resolve().parents[1] / "prompts" / "system.md"
        definition = AgentDefinition(
            name="default",
            display_name="Default",
            description="General-purpose coding and workspace agent.",
            prompt_file=prompt_file,
            tools=None,
        )
        return cls({"default": definition}, "default")

    @classmethod
    def _parse_entry(
        cls,
        entry: object,
        *,
        base_dir: Path,
        manifest_path: Path,
    ) -> AgentDefinition:
        if not isinstance(entry, dict):
            raise ValueError(f"Each agent entry must be a mapping in {manifest_path}")
        name = entry.get("name")
        if not isinstance(name, str) or not _NAME_RE.match(name):
            raise ValueError(f"Invalid agent type name {name!r} in {manifest_path} (use [a-z0-9_-]+)")

        prompt_file_raw = entry.get("prompt_file")
        if not isinstance(prompt_file_raw, str) or not prompt_file_raw.strip():
            raise ValueError(f"Agent type '{name}' is missing 'prompt_file' in {manifest_path}")
        prompt_file = (base_dir / prompt_file_raw).resolve()
        if not prompt_file.exists():
            raise ValueError(f"Agent type '{name}' prompt file not found: {prompt_file}")

        tools = cls._parse_tools(entry.get("tools"), name=name, manifest_path=manifest_path)

        return AgentDefinition(
            name=name,
            display_name=str(entry.get("display_name") or name),
            description=str(entry.get("description") or ""),
            prompt_file=prompt_file,
            tools=tools,
        )

    @staticmethod
    def _parse_tools(
        raw: object,
        *,
        name: str,
        manifest_path: Path,
    ) -> tuple[str, ...] | None:
        if raw is None or raw == "*":
            return None
        if not isinstance(raw, list):
            raise ValueError(
                f"Agent type '{name}' tools must be '*' or a list in {manifest_path}",
            )
        names: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                raise ValueError(f"Agent type '{name}' has a non-string tool entry in {manifest_path}")
            if item not in KNOWN_TOOL_NAMES:
                raise ValueError(
                    f"Agent type '{name}' references unknown tool '{item}' in {manifest_path}",
                )
            names.append(item)
        return tuple(names)

    @property
    def default_name(self) -> str:
        return self._default_name

    def names(self) -> list[str]:
        return list(self._definitions)

    def definitions(self) -> list[AgentDefinition]:
        return list(self._definitions.values())

    def get(self, name: str | None) -> AgentDefinition:
        """Resolve a type by name, falling back to the default for unknown names."""
        if name and name in self._definitions:
            return self._definitions[name]
        return self._definitions[self._default_name]

    def load_prompt(self, name: str | None) -> str:
        return self.get(name).load_prompt()

    def allowed_tools(self, name: str | None) -> tuple[str, ...] | None:
        return self.get(name).tools
