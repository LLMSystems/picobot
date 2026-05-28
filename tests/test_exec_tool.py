import asyncio
from pathlib import Path
import re
import sys

import pytest

from simplified_chatbot.tools.exec_session import (
    ExecSessionManager,
    ListExecSessionsTool,
    WriteStdinTool,
)
from simplified_chatbot.tools.filesystem import build_default_tool_registry
from simplified_chatbot.tools.shell import ExecTool


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


@pytest.mark.asyncio
async def test_exec_with_yield_time_ms_returns_completed_output_without_session_id(tmp_path: Path):
    tool = ExecTool(workspace=tmp_path, allowed_dir=tmp_path)
    command = _python_command("print('hello session exec')")

    result = await tool.execute(
        command=command,
        yield_time_ms=1000,
    )

    assert "hello session exec" in result
    assert "Exit code: 0" in result
    assert "session_id:" not in result


@pytest.mark.asyncio
async def test_exec_with_yield_time_ms_returns_running_session_id(tmp_path: Path):
    tool = ExecTool(workspace=tmp_path, allowed_dir=tmp_path)
    command = _python_command("import time; print('ready', flush=True); time.sleep(0.3)")

    result = await tool.execute(
        command=command,
        yield_time_ms=100,
    )

    assert "ready" in result
    assert "Process running. session_id:" in result
    assert "Elapsed:" in result
    await asyncio.sleep(0.35)


def test_exec_can_continue_with_stdin(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    command = _python_command(
        "import sys; print('ready', flush=True); line=sys.stdin.readline(); print('got:' + line.strip(), flush=True)"
    )

    initial = registry.execute(
        "exec",
        {
            "command": command,
            "yield_time_ms": 100,
        },
    )
    session_id = _session_id(initial)
    result = registry.execute(
        "write_stdin",
        {
            "session_id": session_id,
            "chars": "ping\n",
            "yield_time_ms": 1000,
        },
    )

    assert "got:ping" in result
    assert "Exit code: 0" in result


def test_write_stdin_can_close_stdin(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    command = _python_command(
        "import sys; print('ready', flush=True); data=sys.stdin.read(); print('got:' + data, flush=True)"
    )

    initial = registry.execute(
        "exec",
        {
            "command": command,
            "yield_time_ms": 100,
        },
    )
    session_id = _session_id(initial)
    result = registry.execute(
        "write_stdin",
        {
            "session_id": session_id,
            "chars": "alpha",
            "close_stdin": True,
            "yield_time_ms": 1000,
        },
    )

    assert "Stdin closed." in result
    assert "got:alpha" in result
    assert "Exit code: 0" in result


def test_list_exec_sessions_reports_running_session(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    command = _python_command("import time; print('ready', flush=True); time.sleep(0.3)")

    initial = registry.execute(
        "exec",
        {
            "command": command,
            "yield_time_ms": 100,
        },
    )
    session_id = _session_id(initial)
    listing = registry.execute("list_exec_sessions", {})
    cleanup = registry.execute(
        "write_stdin",
        {
            "session_id": session_id,
            "terminate": True,
            "yield_time_ms": 0,
        },
    )

    assert session_id in listing
    assert "running" in listing
    assert "| cwd=" in listing
    assert "Session terminated." in cleanup


def test_write_stdin_reports_missing_session(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "write_stdin",
        {
            "session_id": "missing",
            "chars": "",
        },
    )

    assert "exec session not found" in result


@pytest.mark.asyncio
async def test_exec_session_tools_enforce_owner_session(tmp_path: Path):
    manager = ExecSessionManager()
    owner_a = "session-a"
    owner_b = "session-b"
    exec_a = ExecTool(
        workspace=tmp_path,
        allowed_dir=tmp_path,
        session_manager=manager,
        owner_session_id=owner_a,
    )
    write_a = WriteStdinTool(manager=manager, owner_session_id=owner_a)
    write_b = WriteStdinTool(manager=manager, owner_session_id=owner_b)
    list_a = ListExecSessionsTool(manager=manager, owner_session_id=owner_a)
    list_b = ListExecSessionsTool(manager=manager, owner_session_id=owner_b)
    command = _python_command("import time; print('ready', flush=True); time.sleep(0.5)")

    initial = await exec_a.execute(
        command=command,
        yield_time_ms=100,
    )
    session_id = _session_id(initial)
    listing_a = await list_a.execute()
    listing_b = await list_b.execute()
    forbidden = await write_b.execute(
        session_id=session_id,
        chars="",
        yield_time_ms=0,
    )
    cleanup = await write_a.execute(
        session_id=session_id,
        terminate=True,
        yield_time_ms=0,
    )

    assert session_id in listing_a
    assert listing_b == "No active exec sessions."
    assert "exec session not found" in forbidden
    assert "Session terminated." in cleanup


def _python_command(code: str) -> str:
    escaped = code.replace('"', '\\"')
    return f'"{sys.executable}" -c "{escaped}"'


def _session_id(output: str) -> str:
    match = re.search(r"session_id:\s*([0-9a-f]+)", output)
    assert match is not None
    return match.group(1)
