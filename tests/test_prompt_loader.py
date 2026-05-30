from simplified_chatbot.config.schema import ChatbotConfig
from simplified_chatbot.prompts.loader import (
    load_subagent_system_prompt,
    load_system_prompt,
)


def test_system_prompt_override_wins():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        system_prompt="Inline prompt",
        system_prompt_file="ignored.md",
    )

    prompt = load_system_prompt(config)

    assert prompt.startswith("Inline prompt")
    assert "You are a practical coding assistant." not in prompt.splitlines()[0]


def test_system_prompt_file_is_resolved_relative_to_config(tmp_path):
    prompt_file = tmp_path / "prompts" / "custom.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("Custom prompt", encoding="utf-8")

    config = ChatbotConfig(
        model="gpt-4.1-mini",
        system_prompt_file="prompts/custom.md",
    )
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    prompt = load_system_prompt(config, config_path=config_path)

    assert prompt.startswith("Custom prompt")


def test_system_prompt_includes_active_skill_and_available_summary():
    config = ChatbotConfig(
        model="gpt-4.1-mini",
        enabled_skills=["math-tutor"],
    )

    prompt = load_system_prompt(config)

    assert "# Active Skills" in prompt
    assert "### Skill: concise-writer" in prompt
    assert "### Skill: math-tutor" in prompt
    assert "# Available Skills" in prompt
    assert "**tool-use-reminder**" in prompt
    assert "tool-use-reminder/SKILL.md" not in prompt


def test_system_prompt_includes_runtime_context_and_platform_policy(tmp_path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")

    prompt = load_system_prompt(config, config_path=config_path)

    assert "## Runtime Context" in prompt
    assert f"Current workspace: `{tmp_path.resolve()}`" in prompt
    assert "## Platform Policy" in prompt


def test_system_prompt_uses_explicit_workspace_when_provided(tmp_path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    session_workspace = tmp_path / "workspaces" / "session-1"
    session_workspace.mkdir(parents=True)

    prompt = load_system_prompt(
        config,
        config_path=config_path,
        workspace=session_workspace,
    )

    assert f"Current workspace: `{session_workspace.resolve()}`" in prompt


def test_system_prompt_mentions_read_skill_tool_rules():
    config = ChatbotConfig(model="gpt-4.1-mini")

    prompt = load_system_prompt(config)

    assert "`read_skill(name)`" in prompt
    assert "`exec(command, working_dir, timeout, yield_time_ms, max_output_chars)`" in prompt
    assert "`write_stdin(session_id, chars, close_stdin, terminate, yield_time_ms, max_output_chars)`" in prompt
    assert "`list_exec_sessions()`" in prompt
    assert "`read_document(path, pages, sheet, range)`" in prompt
    assert "`apply_patch(edits, dry_run)`" in prompt
    assert "`tavily_search(query, topic, search_depth, max_results" in prompt
    assert "`glob(pattern, path, query, type, entry_type, sort, head_limit, offset)`" in prompt
    assert "`spawn(task, label, temperature, model)`" in prompt
    assert "`list_subagents(phase, limit, include_completed)`" in prompt
    assert "`subagent_wait(task_id, timeout_seconds, include_result, tail_tool_events)`" in prompt
    assert "`cancel_subagent(task_id)`" in prompt
    assert "background subagent" in prompt
    assert "`.subagents/<task_id>/`" in prompt
    assert "Use `exec(...)` without `yield_time_ms` for ordinary one-shot commands." in prompt
    assert "Use `write_stdin(...)` to continue, poll, close stdin, or terminate an existing exec session." in prompt
    assert "Prefer `apply_patch` for multi-file changes" in prompt
    assert "Do not try to force binary office/document formats through `read_file`." in prompt
    assert "Do not use `read_file` to access `SKILL.md` files" in prompt


def test_system_prompt_includes_subagent_delegation_policy():
    config = ChatbotConfig(model="gpt-4.1-mini")

    prompt = load_system_prompt(config)

    assert "## Subagent Delegation Policy" in prompt
    assert "remember the returned `task_id`" in prompt
    assert "Use `cancel_subagent(task_id)` when a background task is no longer useful" in prompt
    assert "Do not tell the user that a subagent completed the task unless you have actually checked its result." in prompt
    assert "If `subagent_wait(...)` returns `completed=false`, treat that as still in progress rather than failure." in prompt


def test_system_prompt_includes_exec_session_guidance():
    config = ChatbotConfig(model="gpt-4.1-mini")

    prompt = load_system_prompt(config)

    assert "Use `yield_time_ms` only when you intentionally want session-mode behavior" in prompt
    assert "If `exec(..., yield_time_ms=...)` returns a running `session_id`, continue with `write_stdin(...)`" in prompt
    assert "Use `chars=\"\"` with `write_stdin(...)` when you only need to poll new output" in prompt
    assert "Use `list_exec_sessions()` when you need to recover a session id" in prompt


def test_subagent_system_prompt_includes_runtime_context_and_policy(tmp_path):
    config = ChatbotConfig(model="gpt-4.1-mini")
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    sub_workspace = tmp_path / "workspaces" / "session-1" / ".subagents" / "sub_1234"
    sub_workspace.mkdir(parents=True)

    prompt = load_subagent_system_prompt(
        config,
        config_path=config_path,
        workspace=sub_workspace,
    )

    assert "You are a subagent working for the main Picobot agent." in prompt
    assert f"Current workspace: `{sub_workspace.resolve()}`" in prompt
    assert "## Subagent Policy" in prompt
    assert "Do not spawn another subagent." in prompt
    assert "Your final response is for the main agent, not the end user." in prompt


def test_subagent_system_prompt_includes_available_skills():
    config = ChatbotConfig(model="gpt-4.1-mini")

    prompt = load_subagent_system_prompt(config)

    assert "# Available Skills" in prompt
    assert "`read_skill(name)`" in prompt
    assert "**tool-use-reminder**" in prompt
