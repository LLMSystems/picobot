from pathlib import Path

from simplified_chatbot.tools.filesystem import build_default_tool_registry


def test_edit_file_warns_if_file_not_read_first(tmp_path: Path):
    file_path = tmp_path / "app.py"
    file_path.write_text("hello world\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {"path": str(file_path), "old_text": "world", "new_text": "earth"},
    )

    assert "Successfully edited" in result
    assert "not been read yet" in result
    assert file_path.read_text(encoding="utf-8") == "hello earth\n"


def test_edit_file_after_read_has_no_warning(tmp_path: Path):
    file_path = tmp_path / "app.py"
    file_path.write_text("hello world\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    _ = registry.execute("read_file", {"path": str(file_path)})
    result = registry.execute(
        "edit_file",
        {"path": str(file_path), "old_text": "world", "new_text": "earth"},
    )

    assert "Successfully edited" in result
    assert "not been read yet" not in result
    assert file_path.read_text(encoding="utf-8") == "hello earth\n"


def test_edit_file_replace_all(tmp_path: Path):
    file_path = tmp_path / "app.py"
    file_path.write_text("x=1\nx=1\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {
            "path": str(file_path),
            "old_text": "x=1",
            "new_text": "x=2",
            "replace_all": True,
        },
    )

    assert "Successfully edited" in result
    assert file_path.read_text(encoding="utf-8") == "x=2\nx=2\n"


def test_edit_file_ambiguous_match_requires_context(tmp_path: Path):
    file_path = tmp_path / "dup.py"
    file_path.write_text("aaa\nbbb\naaa\nbbb\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {"path": str(file_path), "old_text": "aaa\nbbb", "new_text": "xxx"},
    )

    assert "appears 2 times" in result
    assert "replace_all=true" in result


def test_edit_file_rejects_ipynb(tmp_path: Path):
    file_path = tmp_path / "analysis.ipynb"
    file_path.write_text('{"cells": []}', encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {"path": str(file_path), "old_text": "x", "new_text": "y"},
    )

    assert "notebook_edit" in result


def test_edit_file_suggests_close_path(tmp_path: Path):
    (tmp_path / "config.py").write_text("x = 1\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {
            "path": str(tmp_path / "conifg.py"),
            "old_text": "x = 1",
            "new_text": "x = 2",
        },
    )

    assert "Error: File not found" in result
    assert "Did you mean" in result
    assert "config.py" in result


def test_edit_file_strips_trailing_whitespace_for_non_markdown(tmp_path: Path):
    file_path = tmp_path / "app.py"
    file_path.write_text("x = 1\n", encoding="utf-8")
    registry = build_default_tool_registry(workspace=tmp_path)

    result = registry.execute(
        "edit_file",
        {
            "path": str(file_path),
            "old_text": "x = 1",
            "new_text": "x = 2   \ny = 3  ",
        },
    )

    assert "Successfully edited" in result
    assert file_path.read_text(encoding="utf-8") == "x = 2\ny = 3\n"

