from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from .config import ScopeConfig, ScopeMode, matches_any

ReadView = Literal["hit", "around", "full"]


class ScopedReadError(RuntimeError):
    """Raised when a requested Markdown read is outside the configured scope."""


@dataclass(frozen=True)
class ReadViewResult:
    namespace: str
    relative_path: str
    view: ReadView
    text: str
    line_start: int
    line_end: int
    total_lines: int
    truncated: bool = False


def read_markdown_view(
    scope: ScopeConfig,
    relative_path: str,
    *,
    view: ReadView = "hit",
    line_start: int | None = None,
    line_end: int | None = None,
    context_lines: int = 20,
    max_chars: int = 50_000,
) -> ReadViewResult:
    """Read a configured Markdown file with bounded hit/around/full views.

    Line numbers are one-based and inclusive. `hit` returns the requested line
    range, `around` expands it by `context_lines`, and `full` returns the whole
    configured file subject to `max_chars`.
    """

    if view not in {"hit", "around", "full"}:
        raise ValueError("view must be hit, around, or full")
    if context_lines < 0:
        raise ValueError("context_lines must be >= 0")
    if max_chars <= 0:
        raise ValueError("max_chars must be > 0")

    path, normalized = _resolve_scoped_markdown(scope, relative_path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)

    if view == "full":
        selected_start = 1 if total_lines else 0
        selected_end = total_lines
        selected = "".join(lines)
    else:
        if line_start is None:
            raise ValueError("line_start is required for hit/around")
        if line_end is None:
            line_end = line_start
        if line_start < 1 or line_end < line_start:
            raise ValueError("line range must be one-based and increasing")
        if line_start > total_lines:
            raise ValueError("line_start is beyond end of file")
        line_end = min(line_end, total_lines)
        if view == "around":
            selected_start = max(1, line_start - context_lines)
            selected_end = min(total_lines, line_end + context_lines)
        else:
            selected_start = line_start
            selected_end = line_end
        selected = "".join(lines[selected_start - 1 : selected_end])

    bounded, truncated = _bound_text(selected, max_chars)
    return ReadViewResult(
        namespace=scope.namespace,
        relative_path=normalized,
        view=view,
        text=bounded,
        line_start=selected_start,
        line_end=selected_end,
        total_lines=total_lines,
        truncated=truncated,
    )


def _resolve_scoped_markdown(scope: ScopeConfig, relative_path: str) -> tuple[Path, str]:
    root = scope.root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"scope root does not exist or is not a directory: {root}")

    posix = PurePosixPath(relative_path.replace("\\", "/"))
    if posix.is_absolute() or ".." in posix.parts or str(posix) in {"", "."}:
        raise ScopedReadError("relative_path must stay inside the configured scope")
    if posix.suffix.lower() != ".md":
        raise ScopedReadError("only Markdown files may be read")

    candidate = root.joinpath(*posix.parts)
    if candidate.is_symlink():
        raise ScopedReadError("symlink Markdown files are not readable")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ScopedReadError("resolved path escapes the configured scope") from exc
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(resolved)

    normalized = resolved.relative_to(root).as_posix()
    relative_dir = resolved.parent.relative_to(root).as_posix() or "."
    policy = scope.policy_for(relative_dir)
    if matches_any(normalized, policy.exclude):
        raise ScopedReadError("Markdown file is excluded by scope policy")
    if policy.mode is ScopeMode.INCLUDE_ONLY:
        if not policy.include or not matches_any(normalized, policy.include):
            raise ScopedReadError("Markdown file is not included by scope policy")

    return resolved, normalized


def _bound_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
