import asyncio
from pathlib import Path

from PIL import Image

from simplified_chatbot.agent.types import ToolResult
from simplified_chatbot.tools.image_viewer import ViewImageTool


def _write_png(path: Path, size: tuple[int, int] = (24, 16), color: str = "red") -> None:
    Image.new("RGB", size, color).save(path, format="PNG")


def _run(coro):
    return asyncio.run(coro)


def test_view_image_single_returns_tool_result(tmp_path: Path) -> None:
    _write_png(tmp_path / "shot.png", size=(64, 48))
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=["shot.png"]))

    assert isinstance(result, ToolResult)
    assert len(result.images) == 1
    block = result.images[0]
    assert block["type"] == "image"
    # Resolved absolute path so the provider reads the right file regardless of CWD.
    assert block["path"] == str((tmp_path / "shot.png").resolve())
    assert block["detail"] == "auto"
    assert "64×48" in result.text
    assert "Loaded 1 image" in result.text


def test_view_image_multiple_merges_blocks(tmp_path: Path) -> None:
    _write_png(tmp_path / "a.png")
    _write_png(tmp_path / "b.jpg")
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=["a.png", "b.jpg"], detail="high"))

    assert isinstance(result, ToolResult)
    assert [b["path"] for b in result.images] == [
        str((tmp_path / "a.png").resolve()),
        str((tmp_path / "b.jpg").resolve()),
    ]
    assert all(b["detail"] == "high" for b in result.images)
    assert "Loaded 2 image(s)" in result.text


def test_view_image_accepts_single_string_path(tmp_path: Path) -> None:
    _write_png(tmp_path / "shot.png")
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths="shot.png"))

    assert isinstance(result, ToolResult)
    assert len(result.images) == 1


def test_view_image_unsupported_suffix_rejected(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=["notes.txt"]))

    assert isinstance(result, str)
    assert "Unsupported image format" in result


def test_view_image_missing_file(tmp_path: Path) -> None:
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=["nope.png"]))

    assert isinstance(result, str)
    assert "no readable images" in result


def test_view_image_empty_paths(tmp_path: Path) -> None:
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=[]))

    assert isinstance(result, str)
    assert "non-empty list" in result


def test_view_image_mixed_valid_and_invalid(tmp_path: Path) -> None:
    _write_png(tmp_path / "ok.png")
    tool = ViewImageTool(workspace=tmp_path, allowed_dir=tmp_path)

    result = _run(tool.execute(paths=["ok.png", "missing.png"]))

    # Valid image still ships; the missing one is reported in the summary text.
    assert isinstance(result, ToolResult)
    assert [b["path"] for b in result.images] == [str((tmp_path / "ok.png").resolve())]
    assert "missing.png" in result.text


def test_view_image_is_read_only() -> None:
    tool = ViewImageTool()
    assert tool.read_only is True
    assert tool.name == "view_image"
