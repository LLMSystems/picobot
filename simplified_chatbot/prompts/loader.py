"""Load the effective system prompt for the simplified chatbot."""

from __future__ import annotations

import platform
from pathlib import Path

from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.skills.loader import SkillsLoader


def load_system_prompt(
    config: ChatbotConfig,
    *,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
) -> str:
    """Resolve the final system prompt using config override rules."""
    base_prompt = _resolve_base_prompt(config, config_path=config_path)
    resolved_workspace = _resolve_workspace(workspace, config_path=config_path)
    loader = SkillsLoader(
        skills_dir=_resolve_skills_dir(config, config_path=config_path),
        disabled_skills=set(config.disabled_skills),
    )
    active_skills = _resolve_active_skills(config, loader)
    active_content = loader.load_skills_for_context(active_skills, workspace=resolved_workspace) if active_skills else ""
    summary = loader.build_skills_summary(exclude=set(active_skills), workspace=resolved_workspace)

    parts = [base_prompt]
    parts.extend(
        [
            _build_runtime_context(
                workspace=resolved_workspace,
                skills_dir=_resolve_skills_dir(config, config_path=config_path),
            ),
            _build_platform_policy(),
        ],
    )
    if active_content:
        parts.append("# Active Skills\n\n" + active_content)
    if summary:
        parts.append(
            "# Available Skills\n\n"
            "The following skills can extend your behavior when relevant.\n\n"
            + summary,
        )
    return "\n\n---\n\n".join(parts)


def load_subagent_system_prompt(
    config: ChatbotConfig,
    *,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
) -> str:
    """Build the focused system prompt used by background subagents."""
    base_prompt = _built_in_subagent_prompt_path().read_text(encoding="utf-8").strip()
    resolved_workspace = _resolve_workspace(workspace, config_path=config_path)
    loader = SkillsLoader(
        skills_dir=_resolve_skills_dir(config, config_path=config_path),
        disabled_skills=set(config.disabled_skills),
    )
    summary = loader.build_skills_summary(workspace=resolved_workspace)

    parts = [
        base_prompt,
        _build_runtime_context(
            workspace=resolved_workspace,
            skills_dir=_resolve_skills_dir(config, config_path=config_path),
        ),
        _build_subagent_policy(),
    ]
    if summary:
        parts.append(
            "# Available Skills\n\n"
            "Load a skill with `read_skill(name)` when the task clearly benefits from it.\n\n"
            + summary,
        )
    return "\n\n---\n\n".join(parts)


def _resolve_base_prompt(
    config: ChatbotConfig,
    *,
    config_path: str | Path | None = None,
) -> str:
    if config.system_prompt:
        return config.system_prompt.strip()

    if config.system_prompt_file:
        prompt_path = _resolve_prompt_path(
            config.system_prompt_file,
            config_path=config_path,
        )
        if not prompt_path.exists():
            raise FileNotFoundError(f"System prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8").strip()

    return _built_in_prompt_path().read_text(encoding="utf-8").strip()


def _resolve_prompt_path(
    prompt_path: str | Path,
    *,
    config_path: str | Path | None = None,
) -> Path:
    candidate = Path(prompt_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    if config_path is not None:
        return (Path(config_path).expanduser().resolve().parent / candidate).resolve()
    return (Path.cwd() / candidate).resolve()


def _built_in_prompt_path() -> Path:
    return Path(__file__).with_name("system.md")


def _built_in_subagent_prompt_path() -> Path:
    return Path(__file__).with_name("subagent_system.md")


def _resolve_workspace(
    workspace: str | Path | None,
    *,
    config_path: str | Path | None = None,
) -> Path:
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    if config_path is not None:
        return Path(config_path).expanduser().resolve().parent
    return Path.cwd().resolve()


def _resolve_skills_dir(
    config: ChatbotConfig,
    *,
    config_path: str | Path | None = None,
) -> Path | None:
    if not config.skills_dir:
        return None
    return _resolve_prompt_path(config.skills_dir, config_path=config_path)


def _resolve_active_skills(
    config: ChatbotConfig,
    loader: SkillsLoader,
) -> list[str]:
    active: list[str] = []
    seen: set[str] = set()
    for name in [*loader.get_always_skills(), *config.enabled_skills]:
        if name in seen or name in loader.disabled_skills:
            continue
        if loader.load_skill(name) is None:
            continue
        active.append(name)
        seen.add(name)
    return active


def _build_runtime_context(*, workspace: Path, skills_dir: Path | None) -> str:
    python_runtime = platform.python_version()
    system = platform.system() or "Unknown"
    machine = platform.machine() or "unknown"
    skill_root = str(skills_dir) if skills_dir is not None else "not configured"
    return "\n".join(
        [
            "## Runtime Context",
            "",
            f"- Runtime: {system} {machine}, Python {python_runtime}",
            f"- Current workspace: `{workspace}`",
            "- Treat this workspace as the default root for file and shell operations.",
            "- The current workspace may be a per-session workspace rather than the project root.",
            f"- Custom skills directory: `{skill_root}`",
        ],
    )


def _build_platform_policy() -> str:
    system = platform.system()
    if system == "Windows":
        lines = [
            "## Platform Policy",
            "",
            "- You are running on Windows.",
            "- Do not assume GNU tools such as `grep`, `sed`, or `awk` exist in the shell.",
            "- Prefer built-in file tools over shell commands when they are more reliable.",
            "- If terminal output looks garbled, consider encoding issues before assuming the command failed.",
        ]
    else:
        lines = [
            "## Platform Policy",
            "",
            "- You are running on a POSIX-like system.",
            "- Built-in file tools are usually more reliable than broad shell commands for workspace inspection.",
            "- Prefer simple UTF-8-safe shell commands when shell execution is necessary.",
        ]
    return "\n".join(lines)


def _build_subagent_policy() -> str:
    return "\n".join(
        [
            "## Subagent Policy",
            "",
            "- Return results to the main agent rather than writing for the end user.",
            "- Do not spawn another subagent.",
            "- Prefer working inside the current subagent workspace unless the task clearly requires reading parent files.",
            "- Keep outputs concise, concrete, and easy for the main agent to reuse.",
        ],
    )
