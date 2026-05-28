"""Minimal filesystem tools (V1): read/write/edit/list operations."""

from __future__ import annotations

import difflib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.file_state import FileStates
from simplified_chatbot.tools.registry import ToolRegistry

_FS_WORKSPACE_BOUNDARY_NOTE = (
    " (this is a hard policy boundary, not a transient failure; "
    "do not retry with shell tricks or alternative tools)"
)

_BLOCKED_DEVICE_PATHS = frozenset(
    {
        "/dev/zero",
        "/dev/random",
        "/dev/urandom",
        "/dev/full",
        "/dev/stdin",
        "/dev/stdout",
        "/dev/stderr",
        "/dev/tty",
        "/dev/console",
        "/dev/fd/0",
        "/dev/fd/1",
        "/dev/fd/2",
    },
)

_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    "htmlcov",
}


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _resolve_path(
    path: str,
    workspace: Path | None = None,
    allowed_dir: Path | None = None,
) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute() and workspace is not None:
        p = workspace / p
    resolved = p.resolve()
    if allowed_dir is not None and not _is_under(resolved, allowed_dir):
        raise PermissionError(
            f"Path {path} is outside allowed directory {allowed_dir}"
            + _FS_WORKSPACE_BOUNDARY_NOTE,
        )
    return resolved


def _is_blocked_device(path: str | Path) -> bool:
    raw = str(path)
    try:
        resolved = str(Path(raw).resolve())
    except (OSError, ValueError):
        resolved = raw

    if raw in _BLOCKED_DEVICE_PATHS or resolved in _BLOCKED_DEVICE_PATHS:
        return True
    if re.match(r"/proc/\d+/fd/[012]$", raw) or re.match(r"/proc/self/fd/[012]$", raw):
        return True
    if re.match(r"/proc/\d+/fd/[012]$", resolved) or re.match(r"/proc/self/fd/[012]$", resolved):
        return True
    if resolved.startswith("/dev/"):
        return True
    return False

@tool_parameters(
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file path to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed, default 1).",
                "minimum": 1,
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read (default 2000).",
                "minimum": 1,
            },
            "pages": {
                "type": "string",
                "description": "Reserved for PDF page ranges (not yet supported in V1).",
            },
        },
        "required": ["path"],
    },
)
class ReadFileTool(Tool):
    """Read UTF-8 text files with line-number output and pagination hints."""

    _MAX_CHARS = 128_000
    _DEFAULT_LIMIT = 2000

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
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read UTF-8 text files with optional line pagination. "
            "Text format: LINE_NUM| CONTENT. "
            "Use offset and limit for large files. "
            "Reads exceeding ~128K chars are truncated."
        )

    async def execute(
        self,
        path: str | None = None,
        offset: int = 1,
        limit: int | None = None,
        pages: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if not path:
                return "Error reading file: Unknown path"

            if pages:
                return "Error: pages is not supported by read_file V1 yet."

            if _is_blocked_device(path):
                return (
                    f"Error: Reading {path} is blocked "
                    "(device path that could hang or produce infinite output)."
                )

            fp = _resolve_path(path, self._workspace, self._allowed_dir)
            if _is_blocked_device(fp):
                return (
                    f"Error: Reading {fp} is blocked "
                    "(device path that could hang or produce infinite output)."
                )
            if not fp.exists():
                return f"Error: File not found: {path}"
            if not fp.is_file():
                return f"Error: Not a file: {path}"

            raw = fp.read_bytes()
            if not raw:
                return f"(Empty file: {path})"

            if self._file_states.is_unchanged(fp, offset=offset, limit=limit):
                return f"[File unchanged since last read: {path}]"

            try:
                text_content = raw.decode("utf-8")
            except UnicodeDecodeError:
                return (
                    f"Error: Cannot read binary file {path}. "
                    "Only UTF-8 text is supported in read_file V1."
                )

            text_content = text_content.replace("\r\n", "\n")
            all_lines = text_content.splitlines()
            total = len(all_lines)

            if offset < 1:
                offset = 1
            if offset > total:
                return f"Error: offset {offset} is beyond end of file ({total} lines)"

            start = offset - 1
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            if len(result) > self._MAX_CHARS:
                trimmed: list[str] = []
                chars = 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            if end < total:
                result += (
                    f"\n\n(Showing lines {offset}-{end} of {total}. "
                    f"Use offset={end + 1} to continue.)"
                )
            else:
                result += f"\n\n(End of file - {total} lines total)"

            self._file_states.record_read(fp, offset=offset, limit=limit)
            return result
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error reading file: {exc}"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file path to write.",
            },
            "content": {
                "type": "string",
                "description": "The full file content to write.",
            },
        },
        "required": ["path", "content"],
    },
)
class WriteFileTool(Tool):
    """Write full UTF-8 file contents, creating parent directories as needed."""

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
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file. "
            "Overwrites existing files and creates parent directories when needed. "
            "Prefer edit_file for partial edits."
        )

    async def execute(
        self,
        path: str | None = None,
        content: str | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if not path:
                raise ValueError("Unknown path")
            if content is None:
                raise ValueError("Unknown content")

            fp = _resolve_path(path, self._workspace, self._allowed_dir)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8", newline="")
            self._file_states.record_write(fp)
            return f"Successfully wrote {len(content)} characters to {fp}"
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error writing file: {exc}"


@dataclass(slots=True)
class _MatchSpan:
    start: int
    end: int
    text: str
    line: int


def _leading_ws(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def _find_exact_matches(content: str, old_text: str) -> list[_MatchSpan]:
    matches: list[_MatchSpan] = []
    start = 0
    while True:
        idx = content.find(old_text, start)
        if idx == -1:
            break
        matches.append(
            _MatchSpan(
                start=idx,
                end=idx + len(old_text),
                text=content[idx : idx + len(old_text)],
                line=content.count("\n", 0, idx) + 1,
            ),
        )
        start = idx + max(1, len(old_text))
    return matches


def _find_trim_matches(content: str, old_text: str) -> list[_MatchSpan]:
    old_lines = old_text.splitlines()
    if not old_lines:
        return []

    content_lines = content.splitlines()
    content_lines_keepends = content.splitlines(keepends=True)
    if len(content_lines) < len(old_lines):
        return []

    offsets: list[int] = []
    pos = 0
    for line in content_lines_keepends:
        offsets.append(pos)
        pos += len(line)
    offsets.append(pos)

    stripped_old = [line.strip() for line in old_lines]
    matches: list[_MatchSpan] = []
    window_size = len(stripped_old)
    for i in range(len(content_lines) - window_size + 1):
        window = content_lines[i : i + window_size]
        comparable = [line.strip() for line in window]
        if comparable != stripped_old:
            continue
        start = offsets[i]
        end = offsets[i + window_size]
        if content_lines_keepends[i + window_size - 1].endswith("\n"):
            end -= 1
        matches.append(
            _MatchSpan(
                start=start,
                end=end,
                text=content[start:end],
                line=i + 1,
            ),
        )
    return matches


def _find_matches(content: str, old_text: str) -> list[_MatchSpan]:
    for finder in (_find_exact_matches, _find_trim_matches):
        matches = finder(content, old_text)
        if matches:
            return matches
    return []


def _reindent_like_match(old_text: str, actual_text: str, new_text: str) -> str:
    old_lines = old_text.split("\n")
    actual_lines = actual_text.split("\n")
    if len(old_lines) != len(actual_lines):
        return new_text

    comparable = [
        (old_line, actual_line)
        for old_line, actual_line in zip(old_lines, actual_lines)
        if old_line.strip() and actual_line.strip()
    ]
    if not comparable or any(
        old_line.strip() != actual_line.strip()
        for old_line, actual_line in comparable
    ):
        return new_text

    old_ws = _leading_ws(comparable[0][0])
    actual_ws = _leading_ws(comparable[0][1])
    if actual_ws == old_ws:
        return new_text

    if old_ws:
        if not actual_ws.startswith(old_ws):
            return new_text
        delta = actual_ws[len(old_ws):]
    else:
        delta = actual_ws
    if not delta:
        return new_text
    return "\n".join((delta + line) if line else line for line in new_text.split("\n"))


def _collapse_internal_whitespace(text: str) -> str:
    return "\n".join(" ".join(line.split()) for line in text.splitlines())


def _diagnose_near_match(old_text: str, actual_text: str) -> list[str]:
    hints: list[str] = []
    if old_text.lower() == actual_text.lower() and old_text != actual_text:
        hints.append("letter case differs")
    if _collapse_internal_whitespace(old_text) == _collapse_internal_whitespace(actual_text) and old_text != actual_text:
        hints.append("whitespace differs")
    if old_text.rstrip("\n") == actual_text.rstrip("\n") and old_text != actual_text:
        hints.append("trailing newline differs")
    return hints


def _best_window(old_text: str, content: str) -> tuple[float, int, list[str], list[str]]:
    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = max(1, len(old_lines))

    best_ratio, best_start = -1.0, 0
    best_window_lines: list[str] = []

    for i in range(max(1, len(lines) - window + 1)):
        current = lines[i : i + window]
        ratio = difflib.SequenceMatcher(None, old_lines, current).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, i
            best_window_lines = current

    actual_text = "".join(best_window_lines).replace("\r\n", "\n").rstrip("\n")
    hints = _diagnose_near_match(old_text.replace("\r\n", "\n").rstrip("\n"), actual_text)
    return best_ratio, best_start, best_window_lines, hints


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file path to edit.",
            },
            "old_text": {
                "type": "string",
                "description": "The text to find and replace.",
            },
            "new_text": {
                "type": "string",
                "description": "The text to replace with.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace all occurrences (default false).",
                "default": False,
            },
        },
        "required": ["path", "old_text", "new_text"],
    },
)
class EditFileTool(Tool):
    """Edit UTF-8 text files by replacing old_text with new_text."""

    _MAX_EDIT_FILE_SIZE = 1024 * 1024 * 1024
    _MARKDOWN_EXTS = frozenset({".md", ".mdx", ".markdown"})

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
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing old_text with new_text. "
            "If old_text matches multiple times, provide more context or set replace_all=true."
        )

    @staticmethod
    def _strip_trailing_ws(text: str) -> str:
        return "\n".join(line.rstrip() for line in text.split("\n"))

    async def execute(
        self,
        path: str | None = None,
        old_text: str | None = None,
        new_text: str | None = None,
        replace_all: bool = False,
        **kwargs: Any,
    ) -> str:
        try:
            if not path:
                raise ValueError("Unknown path")
            if old_text is None:
                raise ValueError("Unknown old_text")
            if new_text is None:
                raise ValueError("Unknown new_text")

            if path.endswith(".ipynb"):
                return "Error: This is a Jupyter notebook. Use the notebook_edit tool instead of edit_file."

            fp = _resolve_path(path, self._workspace, self._allowed_dir)

            if not fp.exists():
                if old_text == "":
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    fp.write_text(new_text, encoding="utf-8")
                    self._file_states.record_write(fp)
                    return f"Successfully created {fp}"
                return self._file_not_found_msg(path, fp)

            try:
                fsize = fp.stat().st_size
            except OSError:
                fsize = 0
            if fsize > self._MAX_EDIT_FILE_SIZE:
                return (
                    f"Error: File too large to edit ({fsize / (1024**3):.1f} GiB). "
                    "Maximum is 1 GiB."
                )

            if old_text == "":
                raw = fp.read_bytes()
                content = raw.decode("utf-8")
                if content.strip():
                    return f"Error: Cannot create file - {path} already exists and is not empty."
                fp.write_text(new_text, encoding="utf-8")
                self._file_states.record_write(fp)
                return f"Successfully edited {fp}"

            warning = self._file_states.check_read(fp)

            raw = fp.read_bytes()
            uses_crlf = b"\r\n" in raw
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                return (
                    f"Error: Cannot edit binary file {path}. "
                    "Only UTF-8 text is supported in edit_file V1."
                )

            content = content.replace("\r\n", "\n")
            norm_old = old_text.replace("\r\n", "\n")
            matches = _find_matches(content, norm_old)

            if not matches:
                return self._not_found_msg(old_text, content, path)

            count = len(matches)
            if count > 1 and not replace_all:
                line_numbers = [match.line for match in matches]
                preview = ", ".join(f"line {line}" for line in line_numbers[:3])
                if len(line_numbers) > 3:
                    preview += ", ..."
                location_hint = f" at {preview}" if preview else ""
                return (
                    f"Warning: old_text appears {count} times{location_hint}. "
                    "Provide more context to make it unique, or set replace_all=true."
                )

            norm_new = new_text.replace("\r\n", "\n")
            if fp.suffix.lower() not in self._MARKDOWN_EXTS:
                norm_new = self._strip_trailing_ws(norm_new)

            selected = matches if replace_all else matches[:1]
            new_content = content
            for match in reversed(selected):
                replacement = _reindent_like_match(norm_old, match.text, norm_new)
                end = match.end
                if replacement == "" and not match.text.endswith("\n") and content[end:end + 1] == "\n":
                    end += 1
                new_content = new_content[: match.start] + replacement + new_content[end:]

            if uses_crlf:
                new_content = new_content.replace("\n", "\r\n")
            fp.write_bytes(new_content.encode("utf-8"))
            self._file_states.record_write(fp)

            message = f"Successfully edited {fp}"
            if warning:
                message = f"{warning}\n{message}"
            return message
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error editing file: {exc}"

    def _file_not_found_msg(self, path: str, fp: Path) -> str:
        parent = fp.parent
        suggestions: list[str] = []
        if parent.is_dir():
            siblings = [item.name for item in parent.iterdir() if item.is_file()]
            close = difflib.get_close_matches(fp.name, siblings, n=3, cutoff=0.6)
            suggestions = [str(parent / candidate) for candidate in close]
        parts = [f"Error: File not found: {path}"]
        if suggestions:
            parts.append("Did you mean: " + ", ".join(suggestions) + "?")
        return "\n".join(parts)

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        best_ratio, best_start, best_window_lines, hints = _best_window(old_text, content)
        if best_ratio > 0.5:
            diff = "\n".join(
                difflib.unified_diff(
                    old_text.splitlines(keepends=True),
                    best_window_lines,
                    fromfile="old_text (provided)",
                    tofile=f"{path} (actual, line {best_start + 1})",
                    lineterm="",
                ),
            )
            hint_text = ""
            if hints:
                hint_text = "\nPossible cause: " + ", ".join(hints) + "."
            return (
                f"Error: old_text not found in {path}."
                f"{hint_text}\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\n{diff}"
            )
        return f"Error: old_text not found in {path}. Verify the file content."


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The directory path to list.",
            },
            "recursive": {
                "type": "boolean",
                "description": "Recursively list all files (default false).",
                "default": False,
            },
            "max_entries": {
                "type": "integer",
                "description": "Maximum entries to return (default 200).",
                "minimum": 1,
            },
        },
        "required": ["path"],
    },
)
class ListDirTool(Tool):
    """List directory contents with optional recursion."""

    _DEFAULT_MAX = 200

    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
    ) -> None:
        self._workspace = workspace.resolve() if workspace is not None else Path.cwd().resolve()
        self._allowed_dir = (
            allowed_dir.resolve() if allowed_dir is not None else self._workspace
        )

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "List the contents of a directory. "
            "Set recursive=true to explore nested structure. "
            "Common noise directories are auto-ignored."
        )

    async def execute(
        self,
        path: str | None = None,
        recursive: bool = False,
        max_entries: int | None = None,
        **kwargs: Any,
    ) -> str:
        try:
            if path is None:
                raise ValueError("Unknown path")
            directory = _resolve_path(path, self._workspace, self._allowed_dir)
            if not directory.exists():
                return f"Error: Directory not found: {path}"
            if not directory.is_dir():
                return f"Error: Not a directory: {path}"

            cap = max_entries or self._DEFAULT_MAX
            items: list[str] = []
            total = 0

            if recursive:
                for item in sorted(directory.rglob("*")):
                    if any(part in _IGNORE_DIRS for part in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        relative = item.relative_to(directory)
                        items.append(f"{relative}/" if item.is_dir() else str(relative))
            else:
                for item in sorted(directory.iterdir()):
                    if item.name in _IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        prefix = "dir " if item.is_dir() else "file"
                        items.append(f"{prefix} {item.name}")

            if not items and total == 0:
                return f"Directory {path} is empty"

            result = "\n".join(items)
            if total > cap:
                result += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return result
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error listing directory: {exc}"


def build_default_tool_registry(
    workspace: Path | None = None,
    *,
    restrict_to_workspace: bool = True,
    skills_dir: Path | None = None,
    builtin_skills_dir: Path | None = None,
    profile: Literal["main", "subagent"] = "main",
    subagent_manager: Any | None = None,
    subagent_store: Any | None = None,
    session_id: str | None = None,
) -> ToolRegistry:
    """Create a default tool registry for the requested execution profile."""
    from simplified_chatbot.tools.document_readers import (
        ReadDocxTool,
        ReadPdfTool,
        ReadXlsxTool,
    )
    from simplified_chatbot.tools.search import FindFilesTool, GlobTool, GrepTool
    from simplified_chatbot.tools.shell import ExecTool
    from simplified_chatbot.tools.skills import ReadSkillTool
    from simplified_chatbot.tools.spawn import SpawnTool
    from simplified_chatbot.tools.subagents import (
        CancelSubagentTool,
        ListSubagentsTool,
        SubagentStatusTool,
        SubagentWaitTool,
    )
    from simplified_chatbot.tools.tavily import TavilySearchTool

    ws = workspace.resolve() if workspace is not None else Path.cwd().resolve()
    allowed = ws if restrict_to_workspace else None
    file_states = FileStates()
    registry = ToolRegistry()

    if profile not in {"main", "subagent"}:
        raise ValueError(f"Unsupported tool registry profile: {profile}")

    def register_shared_tools() -> None:
        registry.register(ExecTool(workspace=ws, allowed_dir=allowed))
        registry.register(
            ReadSkillTool(
                skills_dir=skills_dir,
                builtin_skills_dir=builtin_skills_dir,
            ),
        )
        registry.register(TavilySearchTool())
        registry.register(ReadFileTool(workspace=ws, allowed_dir=allowed, file_states=file_states))
        registry.register(ReadPdfTool(workspace=ws, allowed_dir=allowed))
        registry.register(ReadDocxTool(workspace=ws, allowed_dir=allowed))
        registry.register(ReadXlsxTool(workspace=ws, allowed_dir=allowed))
        registry.register(WriteFileTool(workspace=ws, allowed_dir=allowed, file_states=file_states))
        registry.register(EditFileTool(workspace=ws, allowed_dir=allowed, file_states=file_states))
        registry.register(ListDirTool(workspace=ws, allowed_dir=allowed))
        registry.register(FindFilesTool(workspace=ws, allowed_dir=allowed))
        registry.register(GlobTool(workspace=ws, allowed_dir=allowed))
        registry.register(GrepTool(workspace=ws, allowed_dir=allowed))

    if profile == "main":
        register_shared_tools()
        if subagent_manager is not None:
            registry.register(
                SpawnTool(
                    subagent_manager,
                    workspace=ws,
                    parent_session_id=session_id,
                ),
            )
            registry.register(
                ListSubagentsTool(
                    subagent_manager,
                    session_id=session_id,
                    store=subagent_store,
                ),
            )
            registry.register(
                SubagentStatusTool(
                    subagent_manager,
                    session_id=session_id,
                    store=subagent_store,
                ),
            )
            registry.register(
                SubagentWaitTool(
                    subagent_manager,
                    session_id=session_id,
                    store=subagent_store,
                ),
            )
            registry.register(
                CancelSubagentTool(
                    subagent_manager,
                    session_id=session_id,
                    store=subagent_store,
                ),
            )
    elif profile == "subagent":
        register_shared_tools()

    return registry
