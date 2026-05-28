"""Structured multi-file patch tool aligned with nanobot apply_patch."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.file_state import FileStates

_FS_WORKSPACE_BOUNDARY_NOTE = (
    " (this is a hard policy boundary, not a transient failure; "
    "do not retry with shell tricks or alternative tools)"
)
_ABSOLUTE_WINDOWS_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(slots=True)
class _PatchSummary:
    action: str
    path: str
    added: int = 0
    deleted: int = 0


class _PatchError(ValueError):
    pass


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _resolve_tool_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute() and workspace is not None:
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if allowed_dir is not None and not _is_under(resolved, allowed_dir):
        raise PermissionError(
            f"Path {path} is outside allowed directory {allowed_dir}"
            + _FS_WORKSPACE_BOUNDARY_NOTE,
        )
    return resolved


def _validate_relative_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        raise _PatchError("patch path cannot be empty")
    if "\0" in normalized:
        raise _PatchError(f"patch path contains a null byte: {path!r}")
    if normalized.startswith(("~", "/", "\\")) or _ABSOLUTE_WINDOWS_RE.match(normalized):
        raise _PatchError(f"patch path must be relative: {path}")
    if any(part == ".." for part in re.split(r"[\\/]+", normalized)):
        raise _PatchError(f"patch path must not contain '..': {path}")
    return normalized


def _text_line_count(text: str) -> int:
    if not text:
        return 0
    return len(text.splitlines())


def _line_diff_stats(before: str, after: str) -> tuple[int, int]:
    before_lines = before.replace("\r\n", "\n").splitlines()
    after_lines = after.replace("\r\n", "\n").splitlines()
    added = 0
    deleted = 0
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, deleted


def _format_summary(summary: _PatchSummary) -> str:
    stats = ""
    if summary.added or summary.deleted:
        stats = f" (+{summary.added}/-{summary.deleted})"
    return f"- {summary.action} {summary.path}{stats}"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "description": "List of structured edits to apply in one patch operation.",
                "minItems": 1,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path to the file to edit.",
                        },
                        "action": {
                            "type": "string",
                            "description": (
                                "Operation type: replace (find and replace text), "
                                "add (append new content or create file), delete (remove text)."
                            ),
                            "enum": ["replace", "add", "delete"],
                        },
                        "old_text": {
                            "type": ["string", "null"],
                            "description": "Exact text to search for. Required for replace and delete.",
                        },
                        "new_text": {
                            "type": ["string", "null"],
                            "description": "Text to replace with or append. Required for replace and add.",
                        },
                    },
                    "required": ["path", "action"],
                },
            },
            "dry_run": {
                "type": "boolean",
                "description": "Validate and summarize the patch without writing files.",
                "default": False,
            },
        },
        "required": ["edits"],
    },
)
class ApplyPatchTool(Tool):
    """Apply structured multi-file text edits with optional dry-run."""

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
        file_states: FileStates | None = None,
    ) -> None:
        self._workspace = workspace.resolve() if workspace is not None else Path.cwd().resolve()
        self._allowed_dir = (
            allowed_dir.resolve() if allowed_dir is not None else self._workspace
        )
        self._file_states = file_states or FileStates()

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return (
            "Default tool for code edits. Supports multi-file changes in a single call. "
            "Provide structured edits with relative paths and add/replace/delete actions. "
            "Set dry_run=true to validate and preview without writing files. "
            "Use edit_file only for small exact replacements."
        )

    async def execute(
        self,
        edits: list[dict[str, Any]] | None = None,
        dry_run: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            if not edits:
                raise _PatchError("must provide edits")

            writes: dict[Path, str] = {}
            deletes: set[Path] = set()
            summaries: list[_PatchSummary] = []

            for edit in edits:
                if not isinstance(edit, dict):
                    raise _PatchError("each edit must be an object")
                raw_path = edit.get("path")
                if not isinstance(raw_path, str):
                    raise _PatchError("path required for edit")
                path = _validate_relative_path(raw_path)
                source = _resolve_tool_path(path, self._workspace, self._allowed_dir)
                action = edit.get("action")
                if not isinstance(action, str):
                    raise _PatchError(f"action required for edit: {path}")

                if action == "add":
                    new_text = edit.get("new_text")
                    if new_text is None:
                        raise _PatchError(f"new_text required for add: {path}")

                    pending = writes.get(source)
                    if pending is not None:
                        content = pending
                        exists = True
                    elif source.exists():
                        raw = source.read_bytes()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            raise _PatchError(f"file is not UTF-8 text: {path}")
                        exists = True
                    else:
                        content = ""
                        exists = False

                    if exists:
                        uses_crlf = "\r\n" in content
                        new_norm = content.replace("\r\n", "\n") + new_text.replace("\r\n", "\n")
                        if new_norm and not new_norm.endswith("\n"):
                            new_norm += "\n"
                        if uses_crlf:
                            new_norm = new_norm.replace("\n", "\r\n")
                        writes[source] = new_norm
                        deletes.discard(source)
                        added, deleted = _line_diff_stats(content, new_norm)
                        action_name = "update"
                    else:
                        new_norm = new_text.replace("\r\n", "\n")
                        if new_norm and not new_norm.endswith("\n"):
                            new_norm += "\n"
                        writes[source] = new_norm
                        deletes.discard(source)
                        added = _text_line_count(new_norm)
                        deleted = 0
                        action_name = "add"

                    summaries.append(
                        _PatchSummary(
                            action=action_name,
                            path=path,
                            added=added,
                            deleted=deleted,
                        )
                    )

                elif action == "replace":
                    old_text = edit.get("old_text") or ""
                    if not old_text:
                        raise _PatchError(f"old_text required for replace: {path}")
                    new_text = edit.get("new_text")
                    if new_text is None:
                        raise _PatchError(f"new_text required for replace: {path}")

                    pending = writes.get(source)
                    if pending is not None:
                        content = pending
                    elif source.exists():
                        raw = source.read_bytes()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            raise _PatchError(f"file is not UTF-8 text: {path}")
                    else:
                        raise _PatchError(f"file to update does not exist: {path}")

                    if pending is None and not source.is_file():
                        raise _PatchError(f"path to update is not a file: {path}")

                    uses_crlf = "\r\n" in content
                    norm_content = content.replace("\r\n", "\n")
                    norm_old = old_text.replace("\r\n", "\n")

                    pos = norm_content.find(norm_old)
                    if pos < 0:
                        raise _PatchError(f"old_text not found in {path}")
                    if norm_content.find(norm_old, pos + 1) >= 0:
                        raise _PatchError(f"old_text appears multiple times in {path}")

                    new_norm = (
                        norm_content[:pos]
                        + new_text.replace("\r\n", "\n")
                        + norm_content[pos + len(norm_old):]
                    )
                    if new_norm and not new_norm.endswith("\n"):
                        new_norm += "\n"
                    if uses_crlf:
                        new_norm = new_norm.replace("\n", "\r\n")

                    writes[source] = new_norm
                    deletes.discard(source)
                    added, deleted = _line_diff_stats(content, new_norm)
                    summaries.append(
                        _PatchSummary(
                            action="update",
                            path=path,
                            added=added,
                            deleted=deleted,
                        )
                    )

                elif action == "delete":
                    old_text = edit.get("old_text") or ""
                    if not old_text:
                        raise _PatchError(f"old_text required for delete: {path}")

                    pending = writes.get(source)
                    if pending is not None:
                        content = pending
                    elif source.exists():
                        raw = source.read_bytes()
                        try:
                            content = raw.decode("utf-8")
                        except UnicodeDecodeError:
                            raise _PatchError(f"file is not UTF-8 text: {path}")
                    else:
                        raise _PatchError(f"file to update does not exist: {path}")

                    if pending is None and not source.is_file():
                        raise _PatchError(f"path to update is not a file: {path}")

                    uses_crlf = "\r\n" in content
                    norm_content = content.replace("\r\n", "\n")
                    norm_old = old_text.replace("\r\n", "\n")

                    pos = norm_content.find(norm_old)
                    if pos < 0:
                        raise _PatchError(f"old_text not found in {path}")
                    if norm_content.find(norm_old, pos + 1) >= 0:
                        raise _PatchError(f"old_text appears multiple times in {path}")

                    if norm_old == norm_content:
                        deletes.add(source)
                        writes.pop(source, None)
                        summaries.append(
                            _PatchSummary(
                                action="delete",
                                path=path,
                                added=0,
                                deleted=_text_line_count(content),
                            )
                        )
                    else:
                        new_norm = norm_content[:pos] + norm_content[pos + len(norm_old):]
                        if new_norm and not new_norm.endswith("\n"):
                            new_norm += "\n"
                        if uses_crlf:
                            new_norm = new_norm.replace("\n", "\r\n")
                        writes[source] = new_norm
                        deletes.discard(source)
                        added, deleted = _line_diff_stats(content, new_norm)
                        summaries.append(
                            _PatchSummary(
                                action="update",
                                path=path,
                                added=added,
                                deleted=deleted,
                            )
                        )
                else:
                    raise _PatchError(f"unknown action: {action}")

            if dry_run:
                return "Patch dry-run succeeded:\n" + "\n".join(
                    _format_summary(summary) for summary in summaries
                )

            backups: dict[Path, bytes | None] = {}
            for path in set(writes) | deletes:
                backups[path] = path.read_bytes() if path.exists() else None

            try:
                for path in deletes:
                    if path.exists():
                        path.unlink()
                for path, content in writes.items():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8", newline="")
            except Exception:
                for path, data in backups.items():
                    if data is None:
                        if path.exists():
                            path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(data)
                raise

            for path in set(writes) | deletes:
                self._file_states.record_write(path)
            return "Patch applied:\n" + "\n".join(
                _format_summary(summary) for summary in summaries
            )
        except PermissionError as exc:
            return f"Error: {exc}"
        except _PatchError as exc:
            return f"Error applying patch: {exc}"
        except Exception as exc:
            return f"Error applying patch: {exc}"
