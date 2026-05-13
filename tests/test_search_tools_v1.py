from pathlib import Path

from simplified_chatbot.tools.filesystem import build_default_tool_registry


def test_list_dir_basic_and_recursive(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x\n", encoding="utf-8")

    registry = build_default_tool_registry(workspace=tmp_path)
    top = registry.execute("list_dir", {"path": str(tmp_path)})
    recursive = registry.execute(
        "list_dir",
        {"path": str(tmp_path), "recursive": True},
    )

    assert "README.md" in top
    assert "src" in top
    assert ".git" not in top
    normalized = recursive.replace("\\", "/")
    assert "src/main.py" in normalized
    assert ".git" not in normalized


def test_glob_supports_head_limit_and_offset(tmp_path: Path):
    (tmp_path / "src").mkdir()
    a = tmp_path / "src" / "a.py"
    b = tmp_path / "src" / "b.py"
    c = tmp_path / "src" / "c.py"
    a.write_text("a\n", encoding="utf-8")
    b.write_text("b\n", encoding="utf-8")
    c.write_text("c\n", encoding="utf-8")

    registry = build_default_tool_registry(workspace=tmp_path)
    result = registry.execute(
        "glob",
        {
            "pattern": "*.py",
            "path": str(tmp_path / "src"),
            "head_limit": 1,
            "offset": 1,
        },
    )

    file_lines = [line for line in result.splitlines() if line.endswith(".py")]
    assert len(file_lines) == 1
    assert "pagination: limit=1, offset=1" in result


def test_grep_defaults_to_files_with_matches(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("match_here\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("match_here\n", encoding="utf-8")

    registry = build_default_tool_registry(workspace=tmp_path)
    result = registry.execute(
        "grep",
        {
            "pattern": "match_here",
            "path": str(tmp_path / "src"),
        },
    )

    assert result.splitlines() == ["src/main.py"]
    assert "1|" not in result


def test_grep_content_mode_with_context_and_glob_filter(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "alpha\nbeta\nmatch_here\ngamma\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("match_here\n", encoding="utf-8")

    registry = build_default_tool_registry(workspace=tmp_path)
    result = registry.execute(
        "grep",
        {
            "pattern": "match_here",
            "path": str(tmp_path),
            "glob": "*.py",
            "output_mode": "content",
            "context_before": 1,
            "context_after": 1,
        },
    )

    assert "src/main.py:3" in result
    assert "  2| beta" in result
    assert "> 3| match_here" in result
    assert "  4| gamma" in result
    assert "README.md" not in result


def test_grep_outside_workspace_is_blocked(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("needle\n", encoding="utf-8")

    registry = build_default_tool_registry(workspace=workspace)
    result = registry.execute(
        "grep",
        {"pattern": "needle", "path": str(outside)},
    )

    assert result.startswith("Error:")
