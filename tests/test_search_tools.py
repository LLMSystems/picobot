from __future__ import annotations

import os
from pathlib import Path

import pytest

from simplified_chatbot.tools.filesystem import build_default_tool_registry
from simplified_chatbot.tools.search import FindFilesTool


@pytest.mark.asyncio
async def test_find_files_filters_by_query_glob_and_type(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "settings_view.tsx").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "src" / "settings_api.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("settings\n", encoding="utf-8")

    tool = FindFilesTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(
        path=".",
        query="settings",
        glob="src/**",
        type="ts",
    )

    assert result.splitlines() == ["src/settings_view.tsx"]


@pytest.mark.asyncio
async def test_find_files_can_include_directories(tmp_path: Path):
    (tmp_path / "src" / "settings").mkdir(parents=True)
    (tmp_path / "src" / "settings" / "index.ts").write_text("export {}\n", encoding="utf-8")

    tool = FindFilesTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(path="src", query="settings", include_dirs=True)

    assert "src/settings/" in result.splitlines()
    assert "src/settings/index.ts" in result.splitlines()


@pytest.mark.asyncio
async def test_find_files_supports_modified_sort_and_pagination(tmp_path: Path):
    (tmp_path / "src").mkdir()
    for idx, name in enumerate(("a.py", "b.py", "c.py"), start=1):
        file_path = tmp_path / "src" / name
        file_path.write_text("pass\n", encoding="utf-8")
        os.utime(file_path, (idx, idx))

    tool = FindFilesTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(
        path="src",
        type="py",
        sort="modified",
        head_limit=1,
        offset=1,
    )

    assert result.splitlines()[0] == "src/b.py"
    assert "pagination: limit=1, offset=1" in result


@pytest.mark.asyncio
async def test_find_files_rejects_paths_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside-find-files.txt"
    outside.write_text("secret\n", encoding="utf-8")

    tool = FindFilesTool(workspace=tmp_path, allowed_dir=tmp_path)
    result = await tool.execute(path=str(outside))

    assert result.startswith("Error:")


def test_default_registry_includes_glob_for_main_and_subagent_profiles(tmp_path: Path):
    main_registry = build_default_tool_registry(workspace=tmp_path, profile="main")
    subagent_registry = build_default_tool_registry(workspace=tmp_path, profile="subagent")

    assert "glob" in main_registry.tool_names
    assert "glob" in subagent_registry.tool_names
    assert "find_files" not in main_registry.tool_names
    assert "find_files" not in subagent_registry.tool_names
