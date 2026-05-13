from pathlib import Path
import sys

from simplified_chatbot.tools.filesystem import build_default_tool_registry


def test_exec_runs_command_and_returns_output(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    command = _python_command("print('hello exec')")

    result = registry.execute("exec", {"command": command})

    assert "hello exec" in result
    assert "Exit code: 0" in result


def test_exec_respects_working_dir(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    subdir = tmp_path / "nested"
    subdir.mkdir()
    target = subdir / "created.txt"
    command = _python_command("from pathlib import Path; Path('created.txt').write_text('ok', encoding='utf-8')")

    result = registry.execute(
        "exec",
        {
            "command": command,
            "working_dir": str(subdir),
        },
    )

    assert "Exit code: 0" in result
    assert target.read_text(encoding="utf-8") == "ok"


def test_exec_blocks_working_dir_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    registry = build_default_tool_registry(workspace=workspace)
    command = _python_command("print('nope')")

    result = registry.execute(
        "exec",
        {
            "command": command,
            "working_dir": str(outside),
        },
    )

    assert "outside the configured workspace" in result


def test_exec_times_out(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    command = _python_command("import time; time.sleep(2)")

    result = registry.execute(
        "exec",
        {
            "command": command,
            "timeout": 1,
        },
    )

    assert "timed out" in result


def test_exec_blocks_dangerous_command(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute("exec", {"command": "rm -rf build"})

    assert "deny pattern filter" in result


def _python_command(code: str) -> str:
    escaped = code.replace('"', '\\"')
    return f'"{sys.executable}" -c "{escaped}"'
