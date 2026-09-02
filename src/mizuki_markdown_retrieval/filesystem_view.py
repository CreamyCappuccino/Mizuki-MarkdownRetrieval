from __future__ import annotations

from pathlib import Path
from typing import Any

from .project_config import ProjectConfig, ProjectConfigError


def resolve_workspace_path(project: ProjectConfig, value: str | Path = ".") -> Path:
    root = project.workspace_root.resolve()
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ProjectConfigError("path is outside the configured workspace root") from exc
    return candidate


def workspace_relative_path(project: ProjectConfig, path: Path) -> str:
    root = project.workspace_root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ProjectConfigError("path is outside the configured workspace root") from exc
    rendered = relative.as_posix()
    return "." if rendered in ("", ".") else rendered


def browse_markdown_workspace(
    project: ProjectConfig,
    path: str = ".",
    *,
    depth: int = 1,
    limit: int = 100,
    include_hidden: bool = False,
) -> dict[str, Any]:
    if not 0 <= depth <= 5:
        raise ValueError("depth must be between 0 and 5")
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    target = resolve_workspace_path(project, path)
    if target.is_symlink():
        raise ProjectConfigError("symlink directories cannot be browsed")
    if not target.exists():
        raise FileNotFoundError(target)
    if not target.is_dir():
        raise NotADirectoryError(target)

    root = project.workspace_root.resolve()
    items: list[dict[str, str]] = []
    truncated = False

    def walk(directory: Path, remaining_depth: int) -> None:
        nonlocal truncated
        if truncated:
            return
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError as exc:
            raise ProjectConfigError(f"failed to browse directory: {workspace_relative_path(project, directory)}") from exc

        for child in children:
            if not include_hidden and child.name.startswith("."):
                continue
            if child.is_symlink():
                continue
            try:
                relative = child.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if child.is_dir():
                items.append({"path": relative, "type": "dir"})
                if len(items) >= limit:
                    truncated = True
                    return
                if remaining_depth > 0:
                    walk(child, remaining_depth - 1)
                    if truncated:
                        return
            elif child.is_file() and child.suffix.lower() == ".md":
                items.append({"path": relative, "type": "md"})
                if len(items) >= limit:
                    truncated = True
                    return

    walk(target, depth)
    return {
        "path": workspace_relative_path(project, target),
        "depth": depth,
        "count": len(items),
        "truncated": truncated,
        "items": items,
    }
