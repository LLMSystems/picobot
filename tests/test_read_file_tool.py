from pathlib import Path

from simplified_chatbot.tools.filesystem import ReadFileTool, build_default_tool_registry
from simplified_chatbot.tools.registry import ToolRegistry


def test_read_file_basic_read_has_line_numbers(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path))

    result = registry.execute("read_file", {"path": str(file_path)})

    assert "1| alpha" in result
    assert "3| gamma" in result
    assert "End of file" in result


def test_read_file_offset_and_limit(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("\n".join(f"line {i}" for i in range(1, 8)), encoding="utf-8")
    registry = ToolRegistry()
    registry.register(ReadFileTool(workspace=tmp_path, allowed_dir=tmp_path))

    result = registry.execute(
        "read_file",
        {"path": str(file_path), "offset": 3, "limit": 2},
    )

    assert "3| line 3" in result
    assert "4| line 4" in result
    assert "5| line 5" not in result
    assert "Use offset=5 to continue" in result


def test_read_file_returns_dedup_stub_on_second_read(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("hello\nworld\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    first = registry.execute("read_file", {"path": str(file_path)})
    second = registry.execute("read_file", {"path": str(file_path)})

    assert "1| hello" in first
    assert "[File unchanged since last read:" in second


def test_read_file_blocks_paths_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    file_path = outside / "secret.txt"
    file_path.write_text("secret", encoding="utf-8")

    registry = build_default_tool_registry(workspace=workspace)
    result = registry.execute("read_file", {"path": str(file_path)})

    assert "Error:" in result
    assert "outside allowed directory" in result
