"""Nanobot-inspired skill loader for simplified_chatbot."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

BUILTIN_SKILLS_DIR = Path(__file__).resolve().parent / "builtins"
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)
_STATE_FILENAME = ".skill_state.json"
_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SkillNameInvalidError(ValueError):
    """Raised when a custom skill name is not a safe directory name."""


class SkillBuiltinReadOnlyError(ValueError):
    """Raised when a builtin skill is targeted by a write/delete operation."""


class SkillNotFoundError(KeyError):
    """Raised when a custom skill does not exist."""


class SkillContentInvalidError(ValueError):
    """Raised when a SKILL.md does not satisfy the required format."""


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
        # Effective disabled set = caller-provided ∪ persisted state file.
        self.disabled_skills = set(disabled_skills or set())
        self.disabled_skills |= self._load_state_disabled()

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

    def load_skills_for_context(
        self,
        skill_names: list[str],
        workspace: Path | None = None,
    ) -> str:
        """Load selected skills for direct prompt injection."""
        parts: list[str] = []
        for name in skill_names:
            markdown = self.load_skill(name)
            if markdown is None:
                continue
            header = f"### Skill: {name}"
            if workspace is not None:
                header += f"\nSkill directory: {workspace / '.skills' / name}"
            parts.append(f"{header}\n\n{self._strip_frontmatter(markdown)}")
        return "\n\n---\n\n".join(parts)

    def build_skills_summary(
        self,
        exclude: set[str] | None = None,
        workspace: Path | None = None,
    ) -> str:
        """Build a summary of visible but not directly loaded skills."""
        lines: list[str] = []
        for entry in self.list_skills():
            name = entry["name"]
            if exclude and name in exclude:
                continue
            metadata = self.get_skill_metadata(name) or {}
            description = str(metadata.get("description") or name)
            if workspace is not None:
                lines.append(
                    f"- **{name}** - {description}"
                    f" (dir: `{workspace / '.skills' / name}`)"
                )
            else:
                lines.append(f"- **{name}** - {description}")
        return "\n".join(lines)

    def copy_to_workspace(self, workspace: Path) -> None:
        """Copy all skill directories into workspace/.skills/."""
        dest = workspace / ".skills"
        if dest.exists():
            return
        dest.mkdir(parents=True, exist_ok=True)
        for entry in self.list_skills():
            src_dir = Path(entry["path"]).parent
            dst_dir = dest / entry["name"]
            if not dst_dir.exists():
                shutil.copytree(src_dir, dst_dir)

    # ----- management API (for the frontend skill library) -----------------

    def list_all_skills(self) -> list[dict[str, object]]:
        """List every skill (builtin + custom) ignoring the disabled filter.

        Each entry carries display metadata plus ``source`` and ``disabled``
        flags so the management UI can show and toggle skills.
        """
        seen: set[str] = set()
        result: list[dict[str, object]] = []
        roots: list[tuple[Path | None, str]] = [
            (self.workspace_skills, "custom"),
            (self.builtin_skills, "builtin"),
        ]
        for base, source in roots:
            for entry in self._skill_entries_from_dir(base, source, skip_names=seen):
                name = entry["name"]
                seen.add(name)
                metadata = self.get_skill_metadata(name) or {}
                result.append(
                    {
                        "name": name,
                        "source": source,
                        "description": str(metadata.get("description") or ""),
                        "always": metadata.get("always") is True,
                        "disabled": name in self.disabled_skills,
                    },
                )
        return result

    def is_custom_skill(self, name: str) -> bool:
        """Whether a skill lives in the writable custom skills directory."""
        if not self.workspace_skills:
            return False
        return (self.workspace_skills / name / "SKILL.md").exists()

    def create_skill(
        self,
        name: str,
        content: str,
        files: dict[str, bytes] | None = None,
    ) -> None:
        """Create or overwrite a custom skill in the writable skills dir."""
        if self.workspace_skills is None:
            raise RuntimeError("No writable skills directory is configured")
        safe = self._validate_name(name)
        self._validate_content(content, skill_name=safe)
        skill_dir = self.workspace_skills / safe
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        for rel_path, data in (files or {}).items():
            target = self._resolve_skill_file(skill_dir, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def delete_skill(self, name: str) -> None:
        """Delete a custom skill. Builtin skills cannot be deleted."""
        safe = self._validate_name(name)
        if self.workspace_skills is None or not self.is_custom_skill(safe):
            if (self.builtin_skills / safe / "SKILL.md").exists():
                raise SkillBuiltinReadOnlyError(
                    f"Skill '{name}' is builtin and cannot be deleted",
                )
            raise SkillNotFoundError(name)
        shutil.rmtree(self.workspace_skills / safe)
        self.set_skill_disabled(safe, False)

    def set_skill_disabled(self, name: str, disabled: bool) -> None:
        """Persist enable/disable state for a skill to the state file."""
        current = self._load_state_disabled()
        if disabled:
            current.add(name)
            self.disabled_skills.add(name)
        else:
            current.discard(name)
            self.disabled_skills.discard(name)
        self._write_state_disabled(current)

    # ----- state file helpers ----------------------------------------------

    @property
    def _state_path(self) -> Path | None:
        if self.workspace_skills is None:
            return None
        return self.workspace_skills / _STATE_FILENAME

    def _load_state_disabled(self) -> set[str]:
        path = self._state_path
        if path is None or not path.exists():
            return set()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        disabled = data.get("disabled") if isinstance(data, dict) else None
        if not isinstance(disabled, list):
            return set()
        return {item for item in disabled if isinstance(item, str)}

    def _write_state_disabled(self, disabled: set[str]) -> None:
        path = self._state_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"disabled": sorted(disabled)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _validate_name(self, name: str) -> str:
        candidate = (name or "").strip()
        if not _SAFE_SKILL_NAME.match(candidate):
            raise SkillNameInvalidError(
                "Skill name must start with a letter or digit and contain only "
                "letters, digits, '-' or '_'",
            )
        return candidate

    @staticmethod
    def _validate_content(content: str, *, skill_name: str) -> None:
        """Enforce the minimum SKILL.md format: frontmatter + description."""
        metadata = _parse_frontmatter(content)
        if metadata is None:
            raise SkillContentInvalidError(
                "SKILL.md must start with a YAML frontmatter block delimited by "
                "'---' lines.",
            )
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip():
            raise SkillContentInvalidError(
                "SKILL.md frontmatter must include a non-empty 'description' field "
                "(it tells the agent when to use this skill).",
            )
        declared_name = metadata.get("name")
        if isinstance(declared_name, str) and declared_name.strip() and declared_name.strip() != skill_name:
            raise SkillContentInvalidError(
                f"Frontmatter 'name: {declared_name.strip()}' must match the skill "
                f"folder name '{skill_name}'.",
            )

    @staticmethod
    def _resolve_skill_file(skill_dir: Path, rel_path: str) -> Path:
        target = (skill_dir / rel_path).resolve()
        root = skill_dir.resolve()
        if root != target and root not in target.parents:
            raise SkillNameInvalidError(f"File path '{rel_path}' escapes the skill directory")
        return target

    def get_skill_metadata(self, name: str) -> dict[str, object] | None:
        """Get parsed frontmatter metadata from a skill."""
        return _parse_frontmatter(self.load_skill(name))

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


def _parse_frontmatter(content: str | None) -> dict[str, object] | None:
    """Parse the YAML-like frontmatter block from SKILL.md content."""
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
