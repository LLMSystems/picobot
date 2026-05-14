"""Skill access tools for simplified_chatbot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from simplified_chatbot.skills.loader import SkillsLoader
from simplified_chatbot.tools.base import Tool, tool_parameters


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The skill name to read, such as tool-use-reminder.",
                "minLength": 1,
            },
        },
        "required": ["name"],
    },
)
class ReadSkillTool(Tool):
    """Read SKILL.md content by skill name without breaking workspace boundaries."""

    def __init__(
        self,
        *,
        skills_dir: Path | None = None,
        builtin_skills_dir: Path | None = None,
    ) -> None:
        self._loader = SkillsLoader(
            skills_dir=skills_dir.resolve() if skills_dir is not None else None,
            builtin_skills_dir=(
                builtin_skills_dir.resolve()
                if builtin_skills_dir is not None
                else None
            ),
        )

    @property
    def name(self) -> str:
        return "read_skill"

    @property
    def description(self) -> str:
        return (
            "Read the full content of a skill by skill name. "
            "Use this for non-active skills instead of reading SKILL.md with read_file."
        )

    async def execute(self, name: str, **kwargs: Any) -> str:
        skill_name = name.strip()
        if not skill_name:
            return "Error: Skill name must not be empty."

        content = self._loader.load_skill(skill_name)
        if content is None:
            available = ", ".join(entry["name"] for entry in self._loader.list_skills())
            suffix = f" Available skills: {available}" if available else ""
            return f"Error: Skill '{skill_name}' not found.{suffix}"
        return content
