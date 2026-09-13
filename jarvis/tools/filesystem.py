"""Sandboxed Filesystem Tools with path-traversal prevention and boundary enforcement."""

import fnmatch
import os
from pathlib import Path
from typing import Any
from jarvis.security.permissions import PermissionLevel
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class PathSecurityError(PermissionError):
    """Raised when a path targets a location outside the permitted workspace."""
    pass


def resolve_safe_path(user_path: str, workspace_root: Path | None = None) -> Path:
    """Resolve and validate that a path is strictly inside the permitted workspace root."""
    root = (workspace_root or Path.cwd()).resolve()
    target = (root / user_path).resolve()

    try:
        # Raises ValueError if target is not relative to root
        target.relative_to(root)
    except ValueError:
        raise PathSecurityError(
            f"Access denied: Target path '{user_path}' resolves to '{target}' which is outside "
            f"permitted workspace root '{root}'."
        )

    return target


class ListDirTool(BaseTool):
    """Lists contents of a directory within the permitted workspace."""

    name = "list_dir"
    description = "List files and subdirectories in a directory within the permitted workspace."
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Relative path to directory within workspace (defaults to root '.')",
                }
            },
            "required": [],
        }

    async def execute(self, path: str = ".", **kwargs) -> ToolResult:
        try:
            safe_path = resolve_safe_path(path, self.workspace_root)
            if not safe_path.exists():
                return ToolResult(success=False, error=f"Directory '{path}' does not exist.")
            if not safe_path.is_dir():
                return ToolResult(success=False, error=f"Path '{path}' is not a directory.")

            entries = []
            for item in safe_path.iterdir():
                entries.append({
                    "name": item.name,
                    "is_directory": item.is_dir(),
                    "size_bytes": item.stat().st_size if item.is_file() else None,
                })

            return ToolResult(success=True, result={"directory": path, "entries": entries, "count": len(entries)})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class ReadFileTool(BaseTool):
    """Reads content from a text file within the permitted workspace."""

    name = "read_file"
    description = "Read full or partial text contents from a file within the permitted workspace."
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to file within workspace",
                },
                "max_lines": {
                    "type": "INTEGER",
                    "description": "Optional maximum number of lines to read (defaults to all)",
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, max_lines: int | None = None, **kwargs) -> ToolResult:
        try:
            safe_path = resolve_safe_path(path, self.workspace_root)
            if not safe_path.exists():
                return ToolResult(success=False, error=f"File '{path}' does not exist.")
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path '{path}' is not a regular file.")

            with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                if max_lines and max_lines > 0:
                    lines = [f.readline() for _ in range(max_lines)]
                    content = "".join(lines)
                else:
                    content = f.read()

            return ToolResult(success=True, result={"path": path, "content": content, "size_chars": len(content)})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class WriteFileTool(BaseTool):
    """Creates or overwrites a text file within the permitted workspace."""

    name = "write_file"
    description = "Create or write content to a file within the permitted workspace."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to file to write",
                },
                "content": {
                    "type": "STRING",
                    "description": "Text content to write into the file",
                },
                "overwrite": {
                    "type": "BOOLEAN",
                    "description": "Whether to overwrite if file already exists (default: false)",
                },
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, overwrite: bool = False, **kwargs) -> ToolResult:
        try:
            safe_path = resolve_safe_path(path, self.workspace_root)
            if safe_path.exists() and not overwrite:
                return ToolResult(
                    success=False,
                    error=f"File '{path}' already exists and overwrite=false was specified.",
                )

            safe_path.parent.mkdir(parents=True, exist_ok=True)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(success=True, result={"path": path, "bytes_written": len(content.encode("utf-8"))})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class ModifyFileTool(BaseTool):
    """Modifies an existing file by replacing a target substring with replacement text."""

    name = "modify_file"
    description = "Modify an existing file within workspace by replacing a target substring with replacement text."
    permission_level = PermissionLevel.MODERATE

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to file within workspace",
                },
                "target": {
                    "type": "STRING",
                    "description": "Exact text to find and replace",
                },
                "replacement": {
                    "type": "STRING",
                    "description": "New replacement text",
                },
            },
            "required": ["path", "target", "replacement"],
        }

    async def execute(self, path: str, target: str, replacement: str, **kwargs) -> ToolResult:
        try:
            safe_path = resolve_safe_path(path, self.workspace_root)
            if not safe_path.exists():
                return ToolResult(success=False, error=f"File '{path}' does not exist.")

            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read()

            if target not in content:
                return ToolResult(success=False, error=f"Target string not found in file '{path}'.")

            updated = content.replace(target, replacement, 1)
            with open(safe_path, "w", encoding="utf-8") as f:
                f.write(updated)

            return ToolResult(success=True, result={"path": path, "modified": True})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class DeleteFileTool(BaseTool):
    """Deletes a file within the permitted workspace (Requires Level 3 Confirmation)."""

    name = "delete_file"
    description = "Delete a file within the workspace. Triggers mandatory human confirmation."
    permission_level = PermissionLevel.HIGH_RISK

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "path": {
                    "type": "STRING",
                    "description": "Path to file to delete",
                }
            },
            "required": ["path"],
        }

    async def execute(self, path: str, **kwargs) -> ToolResult:
        try:
            safe_path = resolve_safe_path(path, self.workspace_root)
            if not safe_path.exists():
                return ToolResult(success=False, error=f"File '{path}' does not exist.")
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path '{path}' is not a regular file. Directory deletion not permitted.")

            safe_path.unlink()
            return ToolResult(success=True, result={"path": path, "deleted": True})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))


class SearchFilesTool(BaseTool):
    """Searches for files matching a filename pattern or containing keyword text."""

    name = "search_files"
    description = "Search for files matching a pattern or containing query text within the workspace."
    permission_level = PermissionLevel.LOW_RISK

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "OBJECT",
            "properties": {
                "pattern": {
                    "type": "STRING",
                    "description": "Filename glob pattern (e.g. '*.py' or '*.txt')",
                },
                "content_query": {
                    "type": "STRING",
                    "description": "Optional text query to match inside file contents",
                },
                "max_results": {
                    "type": "INTEGER",
                    "description": "Maximum number of matching files to return (defaults to 20)",
                },
            },
            "required": ["pattern"],
        }

    async def execute(self, pattern: str, content_query: str | None = None, max_results: int = 20, **kwargs) -> ToolResult:
        try:
            root = (self.workspace_root or Path.cwd()).resolve()
            matches = []

            for dirpath, _, filenames in os.walk(root):
                # Skip hidden/cache folders
                if any(part.startswith(".") or part == "__pycache__" for part in Path(dirpath).parts):
                    continue

                for filename in fnmatch.filter(filenames, pattern):
                    file_path = Path(dirpath) / filename
                    rel_path = file_path.relative_to(root).as_posix()

                    if content_query:
                        try:
                            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                                if content_query.lower() in f.read().lower():
                                    matches.append(rel_path)
                        except Exception:
                            pass
                    else:
                        matches.append(rel_path)

                    if len(matches) >= max_results:
                        break
                if len(matches) >= max_results:
                    break

            return ToolResult(success=True, result={"pattern": pattern, "matches": matches, "count": len(matches)})
        except Exception as ex:
            return ToolResult(success=False, error=str(ex))
