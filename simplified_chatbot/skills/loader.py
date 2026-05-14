"""Nanobot-inspired skill loader for simplified_chatbot."""

from __future__ import annotations

import json
import re
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "builtins"
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


class SkillsLoader:
    """Load builtin and custom skills from SKILL.md files."""

    def __init__(
        self,
        skills_dir: Path | None = None,
        builtin_skills_dir: Path | None = None,
        disabled_skills: set[str] | None = None,
    ) -> None:
        self.workspace_skills = skills_dir
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills = disabled_skills or set()

    def list_skills(self) -> list[dict[str, str]]:
        """List available skills from custom and builtin roots."""
        skills: list[dict[str, str]] = []
        workspace_names: set[str] = set()
        if self.workspace_skills:
            workspace_entries = self._skill_entries_from_dir(
                self.workspace_skills,
                "workspace",
            )
            skills.extend(workspace_entries)
            workspace_names = {entry["name"] for entry in workspace_entries}
        skills.extend(
            self._skill_entries_from_dir(
                self.builtin_skills,
                "builtin",
                skip_names=workspace_names,
            ),
        )
        if self.disabled_skills:
            skills = [item for item in skills if item["name"] not in self.disabled_skills]
        return skills

    def load_skill(self, name: str) -> str | None:
        """Load the raw SKILL.md content by skill name."""
        roots = [root for root in [self.workspace_skills, self.builtin_skills] if root]
        for root in roots:
            path = root / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """Load selected skills for direct prompt injection."""
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]
        return "\n\n---\n\n".join(parts)

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        """Build a summary of visible but not directly loaded skills."""
        lines: list[str] = []
        for entry in self.list_skills():
            name = entry["name"]
            if exclude and name in exclude:
                continue
            metadata = self.get_skill_metadata(name) or {}
            description = str(metadata.get("description") or name)
            lines.append(f"- **{name}** - {description}")
        return "\n".join(lines)

    def get_skill_metadata(self, name: str) -> dict[str, object] | None:
        """Get parsed frontmatter metadata from a skill."""
        content = self.load_skill(name)
        if not content or not content.startswith("---"):
            return None
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            return None
        metadata: dict[str, object] = {}
        for raw_line in match.group(1).splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            metadata[key.strip()] = _parse_frontmatter_value(raw_value.strip())
        return metadata

    def get_always_skills(self) -> list[str]:
        """Return skills marked as always=true."""
        result: list[str] = []
        for entry in self.list_skills():
            metadata = self.get_skill_metadata(entry["name"]) or {}
            if metadata.get("always") is True:
                result.append(entry["name"])
        return result

    def _skill_entries_from_dir(
        self,
        base: Path | None,
        source: str,
        *,
        skip_names: set[str] | None = None,
    ) -> list[dict[str, str]]:
        if base is None or not base.exists():
            return []
        entries: list[dict[str, str]] = []
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if skip_names and name in skip_names:
                continue
            entries.append({"name": name, "path": str(skill_file), "source": source})
        return entries

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML-like frontmatter from markdown content."""
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content


def _parse_frontmatter_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if raw.startswith("[") and raw.endswith("]"):
        try:
            parsed = json.loads(raw)
        except Exception:
            return raw
        return parsed if isinstance(parsed, list) else raw
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    return raw
