from pathlib import Path

from simplified_chatbot.tools.filesystem import build_default_tool_registry


def test_write_file_creates_new_file_and_parent_dirs(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    target = tmp_path / "src" / "new_file.py"

    result = registry.execute(
        "write_file",
        {
            "path": str(target),
            "content": "print('hello')\n",
        },
    )

    assert "Successfully wrote" in result
    assert target.read_text(encoding="utf-8") == "print('hello')\n"


def test_write_file_overwrites_existing_file(tmp_path: Path):
    registry = build_default_tool_registry(workspace=tmp_path)
    target = tmp_path / "config.json"
    target.write_text('{"a": 1}\n', encoding="utf-8")

    result = registry.execute(
        "write_file",
        {
            "path": str(target),
            "content": '{"a": 2}\n',
        },
    )

    assert "Successfully wrote" in result
    assert target.read_text(encoding="utf-8") == '{"a": 2}\n'


def test_write_file_blocks_paths_outside_workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "secret.txt"

    registry = build_default_tool_registry(workspace=workspace)
    result = registry.execute(
        "write_file",
        {
            "path": str(target),
            "content": "secret\n",
        },
    )

    assert "Error:" in result
    assert "outside allowed directory" in result
