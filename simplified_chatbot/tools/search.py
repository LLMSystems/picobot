"""Search tools: find_files, glob, and grep."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from simplified_chatbot.tools.base import Tool, tool_parameters
from simplified_chatbot.tools.filesystem import _IGNORE_DIRS, _resolve_path

_DEFAULT_HEAD_LIMIT = 250
_DEFAULT_FILE_HEAD_LIMIT = 200
_MAX_RESULT_CHARS = 128_000
_MAX_FILE_BYTES = 2_000_000
_TYPE_GLOB_MAP = {
    "py": ("*.py", "*.pyi"),
    "python": ("*.py", "*.pyi"),
    "js": ("*.js", "*.jsx", "*.mjs", "*.cjs"),
    "ts": ("*.ts", "*.tsx", "*.mts", "*.cts"),
    "json": ("*.json",),
    "md": ("*.md", "*.mdx"),
    "markdown": ("*.md", "*.mdx"),
    "go": ("*.go",),
    "rs": ("*.rs",),
    "java": ("*.java",),
    "yaml": ("*.yaml", "*.yml"),
    "yml": ("*.yaml", "*.yml"),
    "toml": ("*.toml",),
}


def _normalize_pattern(pattern: str) -> str:
    return pattern.strip().replace("\\", "/")


def _match_glob(rel_path: str, name: str, pattern: str) -> bool:
    normalized = _normalize_pattern(pattern)
    if not normalized:
        return False
    if "/" in normalized or normalized.startswith("**"):
        return PurePosixPath(rel_path).match(normalized)
    return fnmatch.fnmatch(name, normalized)


def _is_binary(raw: bytes) -> bool:
    if b"\x00" in raw:
        return True
    sample = raw[:4096]
    if not sample:
        return False
    non_text = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return (non_text / len(sample)) > 0.2


def _matches_type(name: str, file_type: str | None) -> bool:
    if not file_type:
        return True
    lowered = file_type.strip().lower()
    if not lowered:
        return True
    patterns = _TYPE_GLOB_MAP.get(lowered, (f"*.{lowered}",))
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)


def _matches_query(rel_path: str, query: str | None) -> bool:
    if not query:
        return True
    haystack = rel_path.lower()
    terms = [part for part in query.lower().split() if part]
    return all(term in haystack for term in terms)


def _paginate(items: list[str], limit: int | None, offset: int) -> tuple[list[str], bool]:
    if limit is None:
        return items[offset:], False
    paged = items[offset : offset + limit]
    truncated = len(items) > offset + limit
    return paged, truncated


def _pagination_note(limit: int | None, offset: int, truncated: bool) -> str | None:
    if truncated:
        if limit is None:
            return f"(pagination: offset={offset})"
        return f"(pagination: limit={limit}, offset={offset})"
    if offset > 0:
        return f"(pagination: offset={offset})"
    return None


class _SearchTool(Tool):
    def __init__(
        self,
        workspace: Path | None = None,
        allowed_dir: Path | None = None,
    ) -> None:
        self._workspace = workspace.resolve() if workspace is not None else Path.cwd().resolve()
        self._allowed_dir = (
            allowed_dir.resolve() if allowed_dir is not None else self._workspace
        )

    def _resolve(self, path: str) -> Path:
        return _resolve_path(path, self._workspace, self._allowed_dir)

    def _display_path(self, target: Path, root: Path) -> str:
        try:
            return target.relative_to(self._workspace).as_posix()
        except ValueError:
            return target.relative_to(root).as_posix()

    def _iter_entries(
        self,
        root: Path,
        *,
        include_files: bool,
        include_dirs: bool,
    ):
        if root.is_file():
            if include_files:
                yield root
            return

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(name for name in dirnames if name not in _IGNORE_DIRS)
            current = Path(dirpath)
            if include_dirs:
                for dirname in dirnames:
                    yield current / dirname
            if include_files:
                for filename in sorted(filenames):
                    yield current / filename

    def _iter_files(self, root: Path):
        yield from self._iter_entries(root, include_files=True, include_dirs=False)


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory or file to search in (default '.').",
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional case-insensitive path fragment search. "
                    "Whitespace-separated terms must all be present."
                ),
            },
            "glob": {
                "type": "string",
                "description": "Optional file filter, e.g. '*.py' or 'tests/**/test_*.py'.",
            },
            "type": {
                "type": "string",
                "description": "Optional file type shorthand, e.g. 'py', 'ts', 'md', 'json'.",
            },
            "include_dirs": {
                "type": "boolean",
                "description": "Include matching directories as well as files (default false).",
                "default": False,
            },
            "sort": {
                "type": "string",
                "enum": ["path", "modified"],
                "description": "Sort by path or most recently modified first (default path).",
            },
            "head_limit": {
                "type": "integer",
                "description": "Maximum number of paths to return (default 200, 0 for all).",
                "minimum": 0,
                "maximum": 1000,
            },
            "offset": {
                "type": "integer",
                "description": "Skip the first N results before applying head_limit.",
                "minimum": 0,
                "maximum": 100000,
            },
        },
    },
)
class FindFilesTool(_SearchTool):
    """Find files by path fragment, glob, or file type."""

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def description(self) -> str:
        return (
            "Find files by path fragment, glob, or file type. "
            "Use this before read_file when the path is uncertain. "
            "Returns workspace-relative paths and skips common noise directories."
        )

    async def execute(
        self,
        path: str = ".",
        query: str | None = None,
        glob: str | None = None,
        type: str | None = None,
        include_dirs: bool = False,
        sort: str = "path",
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        try:
            target = self._resolve(path or ".")
            if not target.exists():
                return f"Error: Path not found: {path}"
            if not (target.is_dir() or target.is_file()):
                return f"Error: Unsupported path: {path}"
            if sort not in {"path", "modified"}:
                return "Error: sort must be 'path' or 'modified'"

            limit = (
                _DEFAULT_FILE_HEAD_LIMIT
                if head_limit is None
                else None if head_limit == 0 else head_limit
            )
            root = target if target.is_dir() else target.parent
            matches: list[tuple[str, float]] = []

            for candidate in self._iter_entries(
                target,
                include_files=True,
                include_dirs=include_dirs,
            ):
                if candidate.is_dir() and not include_dirs:
                    continue
                rel_path = candidate.relative_to(root).as_posix()
                display_path = self._display_path(candidate, root)
                if glob and not _match_glob(rel_path, candidate.name, glob):
                    continue
                if candidate.is_file() and not _matches_type(candidate.name, type):
                    continue
                if candidate.is_dir() and type:
                    continue
                if not _matches_query(display_path, query):
                    continue
                try:
                    mtime = candidate.stat().st_mtime
                except OSError:
                    mtime = 0.0
                if candidate.is_dir():
                    display_path += "/"
                matches.append((display_path, mtime))

            if sort == "modified":
                matches.sort(key=lambda item: (-item[1], item[0]))
            else:
                matches.sort(key=lambda item: item[0])

            ordered = [name for name, _ in matches]
            paged, truncated = _paginate(ordered, limit, offset)
            if not paged:
                return "No files found"
            result = "\n".join(paged)
            if note := _pagination_note(limit, offset, truncated):
                result += f"\n\n{note}"
            return result
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error finding files: {exc}"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Optional glob pattern, e.g. '*.py' or 'tests/**/test_*.py'. "
                    "Omit to list all entries under path and filter via query/type."
                ),
                "minLength": 1,
            },
            "path": {
                "type": "string",
                "description": "Directory to search from (default '.').",
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional case-insensitive path fragment filter. "
                    "Whitespace-separated terms must all be present in the path."
                ),
            },
            "type": {
                "type": "string",
                "description": "Optional file type shorthand, e.g. 'py', 'ts', 'md', 'json'.",
            },
            "entry_type": {
                "type": "string",
                "enum": ["files", "dirs", "both"],
                "description": "Whether to match files, directories, or both (default files).",
            },
            "sort": {
                "type": "string",
                "enum": ["modified", "path"],
                "description": "Sort by mtime (newest first) or path (default modified).",
            },
            "max_results": {
                "type": "integer",
                "description": "Legacy alias for head_limit.",
                "minimum": 1,
                "maximum": 1000,
            },
            "head_limit": {
                "type": "integer",
                "description": "Maximum number of matches to return (default 250, 0 for all).",
                "minimum": 0,
                "maximum": 1000,
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N matching entries.",
                "minimum": 0,
                "maximum": 100000,
            },
        },
    },
)
class GlobTool(_SearchTool):
    """Find paths by glob pattern, optionally filtered by name fragment or file type."""

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find paths by glob pattern, optionally filtered by path fragment (query) "
            "or file type shorthand (type). All filters combine with AND. "
            "Pattern is optional — omit to list entries and rely on query/type. "
            "Results default to modification-time order (newest first). "
            "Skips common noise directories."
        )

    async def execute(
        self,
        pattern: str | None = None,
        path: str = ".",
        query: str | None = None,
        type: str | None = None,
        entry_type: str = "files",
        sort: str = "modified",
        max_results: int | None = None,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        try:
            root = self._resolve(path or ".")
            if not root.exists():
                return f"Error: Path not found: {path}"
            if not root.is_dir():
                return f"Error: Not a directory: {path}"
            if sort not in {"modified", "path"}:
                return "Error: sort must be 'modified' or 'path'"
            if entry_type not in {"files", "dirs", "both"}:
                return "Error: entry_type must be 'files', 'dirs', or 'both'"

            if head_limit is not None:
                limit = None if head_limit == 0 else head_limit
            elif max_results is not None:
                limit = max_results
            else:
                limit = _DEFAULT_HEAD_LIMIT

            include_files = entry_type in {"files", "both"}
            include_dirs = entry_type in {"dirs", "both"}

            matches: list[tuple[str, float]] = []
            for entry in self._iter_entries(
                root,
                include_files=include_files,
                include_dirs=include_dirs,
            ):
                rel_path = entry.relative_to(root).as_posix()
                if pattern and not _match_glob(rel_path, entry.name, pattern):
                    continue
                if entry.is_file() and not _matches_type(entry.name, type):
                    continue
                if entry.is_dir() and type:
                    continue
                display = self._display_path(entry, root)
                if not _matches_query(display, query):
                    continue
                if entry.is_dir():
                    display += "/"
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    mtime = 0.0
                matches.append((display, mtime))

            if not matches:
                filters = pattern or query or type or "(no filter)"
                return f"No paths matched {filters} in {path}"

            if sort == "modified":
                matches.sort(key=lambda item: (-item[1], item[0]))
            else:
                matches.sort(key=lambda item: item[0])
            ordered = [name for name, _ in matches]
            paged, truncated = _paginate(ordered, limit, offset)
            result = "\n".join(paged)
            if note := _pagination_note(limit, offset, truncated):
                result += f"\n\n{note}"
            return result
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error finding files: {exc}"


@tool_parameters(
    {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex or plain text pattern to search for.",
                "minLength": 1,
            },
            "path": {
                "type": "string",
                "description": "File or directory to search (default '.').",
            },
            "glob": {
                "type": "string",
                "description": "Optional file filter, e.g. '*.py'.",
            },
            "type": {
                "type": "string",
                "description": "Optional file type shorthand, e.g. 'py', 'ts', 'md'.",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive search (default false).",
                "default": False,
            },
            "fixed_strings": {
                "type": "boolean",
                "description": "Treat pattern as plain text instead of regex (default false).",
                "default": False,
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "Default files_with_matches.",
            },
            "context_before": {
                "type": "integer",
                "description": "Lines of context before each match.",
                "minimum": 0,
                "maximum": 20,
            },
            "context_after": {
                "type": "integer",
                "description": "Lines of context after each match.",
                "minimum": 0,
                "maximum": 20,
            },
            "max_matches": {
                "type": "integer",
                "description": "Legacy alias for head_limit in content mode.",
                "minimum": 1,
                "maximum": 1000,
            },
            "max_results": {
                "type": "integer",
                "description": "Legacy alias for head_limit in non-content modes.",
                "minimum": 1,
                "maximum": 1000,
            },
            "head_limit": {
                "type": "integer",
                "description": "Maximum returned results (default 250).",
                "minimum": 0,
                "maximum": 1000,
            },
            "offset": {
                "type": "integer",
                "description": "Skip first N results.",
                "minimum": 0,
                "maximum": 100000,
            },
        },
        "required": ["pattern"],
    },
)
class GrepTool(_SearchTool):
    """Search file contents using regex or fixed strings."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search file contents with a regex pattern. "
            "Default output mode returns matching file paths only."
        )

    @staticmethod
    def _format_block(
        display_path: str,
        lines: list[str],
        match_line: int,
        before: int,
        after: int,
    ) -> str:
        start = max(1, match_line - before)
        end = min(len(lines), match_line + after)
        block = [f"{display_path}:{match_line}"]
        for line_no in range(start, end + 1):
            marker = ">" if line_no == match_line else " "
            block.append(f"{marker} {line_no}| {lines[line_no - 1]}")
        return "\n".join(block)

    async def execute(
        self,
        pattern: str,
        path: str = ".",
        glob: str | None = None,
        type: str | None = None,
        case_insensitive: bool = False,
        fixed_strings: bool = False,
        output_mode: str = "files_with_matches",
        context_before: int = 0,
        context_after: int = 0,
        max_matches: int | None = None,
        max_results: int | None = None,
        head_limit: int | None = None,
        offset: int = 0,
        **kwargs: Any,
    ) -> str:
        try:
            target = self._resolve(path or ".")
            if not target.exists():
                return f"Error: Path not found: {path}"
            if not (target.is_dir() or target.is_file()):
                return f"Error: Unsupported path: {path}"

            flags = re.IGNORECASE if case_insensitive else 0
            try:
                needle = re.escape(pattern) if fixed_strings else pattern
                regex = re.compile(needle, flags)
            except re.error as exc:
                return f"Error: invalid regex pattern: {exc}"

            if head_limit is not None:
                limit = None if head_limit == 0 else head_limit
            elif output_mode == "content" and max_matches is not None:
                limit = max_matches
            elif output_mode != "content" and max_results is not None:
                limit = max_results
            else:
                limit = _DEFAULT_HEAD_LIMIT

            blocks: list[str] = []
            result_chars = 0
            seen_content_matches = 0
            truncated = False
            size_truncated = False
            skipped_binary = 0
            skipped_large = 0
            matching_files: list[str] = []
            counts: dict[str, int] = {}
            file_mtimes: dict[str, float] = {}
            root = target if target.is_dir() else target.parent

            for file_path in self._iter_files(target):
                rel_path = file_path.relative_to(root).as_posix()
                if glob and not _match_glob(rel_path, file_path.name, glob):
                    continue
                if not _matches_type(file_path.name, type):
                    continue

                raw = file_path.read_bytes()
                if len(raw) > _MAX_FILE_BYTES:
                    skipped_large += 1
                    continue
                if _is_binary(raw):
                    skipped_binary += 1
                    continue
                try:
                    mtime = file_path.stat().st_mtime
                except OSError:
                    mtime = 0.0
                try:
                    content = raw.decode("utf-8")
                except UnicodeDecodeError:
                    skipped_binary += 1
                    continue

                lines = content.splitlines()
                display_path = self._display_path(file_path, root)
                file_had_match = False
                for idx, line in enumerate(lines, start=1):
                    if not regex.search(line):
                        continue
                    file_had_match = True

                    if output_mode == "count":
                        counts[display_path] = counts.get(display_path, 0) + 1
                        continue

                    if output_mode == "files_with_matches":
                        if display_path not in matching_files:
                            matching_files.append(display_path)
                            file_mtimes[display_path] = mtime
                        break

                    seen_content_matches += 1
                    if seen_content_matches <= offset:
                        continue
                    if limit is not None and len(blocks) >= limit:
                        truncated = True
                        break
                    block = self._format_block(
                        display_path,
                        lines,
                        idx,
                        context_before,
                        context_after,
                    )
                    extra_sep = 2 if blocks else 0
                    if result_chars + extra_sep + len(block) > _MAX_RESULT_CHARS:
                        size_truncated = True
                        break
                    blocks.append(block)
                    result_chars += extra_sep + len(block)

                if output_mode == "count" and file_had_match and display_path not in matching_files:
                    matching_files.append(display_path)
                    file_mtimes[display_path] = mtime
                if truncated or size_truncated:
                    break

            if output_mode == "files_with_matches":
                if not matching_files:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered = sorted(matching_files, key=lambda name: (-file_mtimes.get(name, 0.0), name))
                    paged, truncated = _paginate(ordered, limit, offset)
                    result = "\n".join(paged)
            elif output_mode == "count":
                if not counts:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    ordered = sorted(matching_files, key=lambda name: (-file_mtimes.get(name, 0.0), name))
                    paged, truncated = _paginate(ordered, limit, offset)
                    result = "\n".join(f"{name}: {counts[name]}" for name in paged)
            else:
                if not blocks:
                    result = f"No matches found for pattern '{pattern}' in {path}"
                else:
                    result = "\n\n".join(blocks)

            notes: list[str] = []
            if output_mode == "content" and truncated:
                notes.append(f"(pagination: limit={limit}, offset={offset})")
            elif output_mode == "content" and size_truncated:
                notes.append("(output truncated due to size)")
            elif output_mode in {"files_with_matches", "count"}:
                if note := _pagination_note(limit, offset, truncated):
                    notes.append(note)
            if skipped_binary:
                notes.append(f"(skipped {skipped_binary} binary/unreadable files)")
            if skipped_large:
                notes.append(f"(skipped {skipped_large} large files)")
            if output_mode == "count" and counts:
                notes.append(f"(total matches: {sum(counts.values())} in {len(counts)} files)")
            if notes:
                result += "\n\n" + "\n".join(notes)
            return result
        except PermissionError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            return f"Error searching files: {exc}"

