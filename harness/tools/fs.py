"""
harness/tools/fs.py — Safe Local Filesystem Tools.
Provides read_file, write_file, edit_file (search-replace with diff generation), list_dir, and grep_search.
All operations are sandboxed to the local workspace root.
"""

import difflib
import fnmatch
import os
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from harness.tools.sandbox import validate_workspace_path


def read_file(
    path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """Read contents of a file, optionally within [start_line, end_line] (1-indexed)."""
    target = validate_workspace_path(path, workspace_root)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: '{path}'")

    with open(target, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    total_lines = len(lines)
    start = max(1, start_line) if start_line else 1
    end = min(total_lines, end_line) if end_line else total_lines

    if start > total_lines:
        content_lines = []
    else:
        content_lines = lines[start - 1 : end]

    numbered = [f"{i + start}: {line}" for i, line in enumerate(content_lines)]

    return {
        "path": str(target.relative_to(Path(workspace_root).resolve())),
        "total_lines": total_lines,
        "displayed_range": [start, end],
        "content": "".join(numbered),
        "raw_content": "".join(content_lines),
    }


def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """Create a new file or overwrite an existing file."""
    target = validate_workspace_path(path, workspace_root, allow_write_to_new_file=True)

    if target.exists() and not overwrite:
        raise FileExistsError(f"File already exists: '{path}'. Set overwrite=True to replace.")

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)

    return {
        "path": str(target.relative_to(Path(workspace_root).resolve())),
        "bytes_written": len(content.encode("utf-8")),
        "status": "overwritten" if target.exists() and overwrite else "created",
    }


def edit_file(
    path: str,
    old_str: str,
    new_str: str,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """
    Surgical search-and-replace inside an existing file.
    Generates unified diff of the change.
    """
    target = validate_workspace_path(path, workspace_root)
    if not target.is_file():
        raise FileNotFoundError(f"File not found: '{path}'")

    with open(target, "r", encoding="utf-8", errors="replace") as f:
        original = f.read()

    # 1. Exact match
    count = original.count(old_str)
    if count == 0:
        # Fallback: Check if line-ending or leading/trailing whitespace difference exists
        normalized_orig = original.replace("\r\n", "\n")
        normalized_old = old_str.replace("\r\n", "\n")
        if normalized_old in normalized_orig:
            original = normalized_orig
            old_str = normalized_old
            new_str = new_str.replace("\r\n", "\n")
            count = original.count(old_str)
        else:
            raise ValueError(
                f"Cannot find exact match for 'old_str' in '{path}'. "
                "Ensure indentation and surrounding context match exactly."
            )

    if count > 1:
        raise ValueError(
            f"Found {count} occurrences of 'old_str' in '{path}'. "
            "Please include more surrounding context lines to make it uniquely identifiable."
        )

    updated = original.replace(old_str, new_str, 1)

    # Generate unified diff for review
    orig_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)
    rel_path = str(target.relative_to(Path(workspace_root).resolve()))

    diff = "".join(
        difflib.unified_diff(
            orig_lines,
            updated_lines,
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
    )

    with open(target, "w", encoding="utf-8") as f:
        f.write(updated)

    return {
        "path": rel_path,
        "diff": diff,
        "status": "applied",
    }


def list_dir(
    path: str = ".",
    pattern: str = "*",
    max_results: int = 100,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """List directory contents with optional glob filtering."""
    target = validate_workspace_path(path, workspace_root)
    if not target.is_dir():
        raise NotADirectoryError(f"Directory not found: '{path}'")

    results = []
    root = Path(workspace_root).resolve()

    for item in sorted(target.iterdir()):
        if item.name.startswith(".") and item.name in (".git", ".ssh"):
            continue
        if fnmatch.fnmatch(item.name, pattern):
            results.append({
                "name": item.name,
                "path": str(item.relative_to(root)),
                "is_dir": item.is_dir(),
                "size_bytes": item.stat().st_size if item.is_file() else None,
            })
            if len(results) >= max_results:
                break

    return {
        "path": str(target.relative_to(root)),
        "count": len(results),
        "entries": results,
    }


def grep_search(
    query: str,
    path: str = ".",
    max_results: int = 50,
    workspace_root: str = ".",
) -> Dict[str, Any]:
    """Search for string or regex pattern across text files in path."""
    target = validate_workspace_path(path, workspace_root)
    root = Path(workspace_root).resolve()

    regex = re.compile(query, re.IGNORECASE)
    matches = []

    files_to_search = [target] if target.is_file() else list(target.rglob("*"))

    for f in files_to_search:
        if not f.is_file():
            continue
        # Skip hidden/binary/git directories
        if any(part.startswith(".") for part in f.relative_to(root).parts):
            continue
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".pyc", ".gguf", ".zip", ".tar", ".gz", ".exe", ".bin"):
            continue

        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as file_obj:
                for line_num, line in enumerate(file_obj, 1):
                    if regex.search(line):
                        matches.append({
                            "file": str(f.relative_to(root)),
                            "line": line_num,
                            "text": line.strip()[:200],
                        })
                        if len(matches) >= max_results:
                            break
        except Exception:
            continue

        if len(matches) >= max_results:
            break

    return {
        "query": query,
        "total_matches": len(matches),
        "matches": matches,
    }
