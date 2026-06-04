"""Image viewer tool for multimodal models.

Unlike the document readers (which extract *text*), this tool feeds raw images
back to the model so a vision-capable model can actually look at them. Because
OpenAI-compatible ``tool`` role messages cannot carry images, the tool returns a
:class:`~simplified_chatbot.agent.types.ToolResult` envelope: a textual summary
plus image content blocks that the agent loop injects as a follow-up ``user``
message.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from simplified_chatbot.agent.types import ContentBlock, ToolResult
from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.document_readers import _validate_path

_SUPPORTED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_DEFAULT_DETAIL = "auto"
_MAX_IMAGES = 8


def _describe_image(fp: Path, display_path: str) -> str:
    """Build a short textual summary for one image (best effort)."""
    size_note = ""
    try:
        from PIL import Image

        with Image.open(fp) as img:
            size_note = f"{img.width}×{img.height} {img.format or fp.suffix.lstrip('.').upper()}, "
    except Exception:
        # PIL missing or unreadable header: still ship the bytes to the model.
        size_note = ""
    byte_note = ""
    try:
        byte_note = f"{fp.stat().st_size} bytes"
    except OSError:
        byte_note = "unknown size"
    return f"- {display_path} ({size_note}{byte_note})"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or more image paths in the workspace to look at. "
                    f"Supported: {', '.join(_SUPPORTED_SUFFIXES)}."
                ),
                "minItems": 1,
                "maxItems": _MAX_IMAGES,
            },
            "detail": {
                "type": "string",
                "enum": ["auto", "low", "high"],
                "description": "Vision detail level. Default 'auto'.",
            },
        },
        "required": ["paths"],
    },
)
class ViewImageTool(Tool):
    """Load workspace images so a vision-capable model can see them.

    Requires a multimodal model; the loaded images are attached to the
    conversation as a user message after the tool result.
    """

    read_only = True

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
    ) -> None:
        self._workspace = workspace.resolve() if workspace is not None else Path.cwd().resolve()
        self._allowed_dir = allowed_dir.resolve() if allowed_dir is not None else self._workspace

    @property
    def name(self) -> str:
        return "view_image"

    @property
    def description(self) -> str:
        return (
            "Look at one or more image files (.png, .jpg, .jpeg, .gif, .webp, .bmp) "
            "from the workspace. The images are attached for you to see directly; "
            "requires a vision-capable model. Use read_document for PDFs/Office files "
            "and read_file for text."
        )

    async def execute(
        self,
        paths: list[str] | str | None = None,
        detail: Literal["auto", "low", "high"] | None = None,
        **kwargs: Any,
    ) -> ToolResult | str:
        candidates = self._coerce_paths(paths)
        if not candidates:
            return "Error: 'paths' must be a non-empty list of image paths."
        if len(candidates) > _MAX_IMAGES:
            return f"Error: too many images ({len(candidates)}); limit is {_MAX_IMAGES} per call."

        resolved_detail = detail if detail in {"auto", "low", "high"} else _DEFAULT_DETAIL
        summaries: list[str] = []
        images: list[ContentBlock] = []
        for raw_path in candidates:
            fp, error = _validate_path(raw_path, self._workspace, self._allowed_dir)
            if error:
                summaries.append(f"- {raw_path}: {error}")
                continue
            if fp.suffix.lower() not in _SUPPORTED_SUFFIXES:
                summaries.append(
                    f"- {raw_path}: Error: Unsupported image format '{fp.suffix or '(none)'}'. "
                    f"Supported: {', '.join(_SUPPORTED_SUFFIXES)}.",
                )
                continue
            summaries.append(_describe_image(fp, raw_path))
            # Store the resolved absolute path (not the model-supplied relative
            # one) so the provider reads the right file regardless of the server
            # process CWD — mirrors how user-attached images are resolved in
            # _build_chat_content.
            block: ContentBlock = {
                "type": "image",
                "path": str(fp),
                "detail": resolved_detail,
            }
            images.append(block)

        if not images:
            return "Error: no readable images.\n" + "\n".join(summaries)

        header = (
            f"Loaded {len(images)} image(s); attached below for viewing."
            if len(images) > 1
            else "Loaded 1 image; attached below for viewing."
        )
        text = header + "\n" + "\n".join(summaries)
        return ToolResult(text=text, images=images)

    @staticmethod
    def _coerce_paths(paths: list[str] | str | None) -> list[str]:
        if paths is None:
            return []
        if isinstance(paths, str):
            return [paths] if paths.strip() else []
        if isinstance(paths, list):
            return [p for p in paths if isinstance(p, str) and p.strip()]
        return []
