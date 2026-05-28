from __future__ import annotations

import asyncio
from pathlib import Path

from simplified_chatbot.tools.apply_patch import ApplyPatchTool


def test_apply_patch_replaces_text(tmp_path: Path):
    target = tmp_path / "calc.py"
    target.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "calc.py",
                    "action": "replace",
                    "old_text": "    return a + b",
                    "new_text": "    return a - b",
                }
            ]
        )
    )

    assert "Patch applied" in result
    assert "update calc.py" in result
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"


def test_apply_patch_adds_new_file(tmp_path: Path):
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "config.py",
                    "action": "add",
                    "new_text": "DEBUG = True",
                }
            ]
        )
    )

    assert "add config.py" in result
    assert (tmp_path / "config.py").read_text(encoding="utf-8") == "DEBUG = True\n"


def test_apply_patch_deletes_entire_file(tmp_path: Path):
    target = tmp_path / "obsolete.txt"
    target.write_text("remove me\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "obsolete.txt",
                    "action": "delete",
                    "old_text": "remove me\n",
                }
            ]
        )
    )

    assert "delete obsolete.txt" in result
    assert not target.exists()


def test_apply_patch_batch_multiple_files(tmp_path: Path):
    first = tmp_path / "a.py"
    first.write_text("X = 1\n", encoding="utf-8")
    second = tmp_path / "b.py"
    second.write_text("from a import X\nprint(X)\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "a.py",
                    "action": "replace",
                    "old_text": "X = 1",
                    "new_text": "Y = 1",
                },
                {
                    "path": "b.py",
                    "action": "replace",
                    "old_text": "from a import X",
                    "new_text": "from a import Y",
                },
            ]
        )
    )

    assert "update a.py" in result
    assert "update b.py" in result
    assert first.read_text(encoding="utf-8") == "Y = 1\n"
    assert second.read_text(encoding="utf-8") == "from a import Y\nprint(X)\n"


def test_apply_patch_dry_run_does_not_write(tmp_path: Path):
    target = tmp_path / "dry.txt"
    target.write_text("before\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "dry.txt",
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                },
                {
                    "path": "added.txt",
                    "action": "add",
                    "new_text": "new",
                },
            ],
            dry_run=True,
        )
    )

    assert "Patch dry-run succeeded" in result
    assert target.read_text(encoding="utf-8") == "before\n"
    assert not (tmp_path / "added.txt").exists()


def test_apply_patch_rolls_back_when_late_operation_fails(tmp_path: Path):
    first = tmp_path / "first.txt"
    first.write_text("before\n", encoding="utf-8")
    tool = ApplyPatchTool(workspace=tmp_path)

    result = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "first.txt",
                    "action": "replace",
                    "old_text": "before",
                    "new_text": "after",
                },
                {
                    "path": "missing.txt",
                    "action": "delete",
                    "old_text": "remove me",
                },
            ]
        )
    )

    assert "file to update does not exist: missing.txt" in result
    assert first.read_text(encoding="utf-8") == "before\n"


def test_apply_patch_rejects_absolute_and_parent_paths(tmp_path: Path):
    tool = ApplyPatchTool(workspace=tmp_path)

    absolute = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "/tmp/owned.txt",
                    "action": "add",
                    "new_text": "nope",
                }
            ]
        )
    )
    parent = asyncio.run(
        tool.execute(
            edits=[
                {
                    "path": "../owned.txt",
                    "action": "add",
                    "new_text": "nope",
                }
            ]
        )
    )

    assert "must be relative" in absolute
    assert "must not contain '..'" in parent
