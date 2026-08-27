from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .config import ScopeConfig, ScopeMode, matches_any
from .models import DocumentRef, IndexedMarkdownFile


def discover_markdown(scope: ScopeConfig) -> list[IndexedMarkdownFile]:
    root = scope.root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"scope root does not exist or is not a directory: {root}")

    discovered: list[IndexedMarkdownFile] = []
    for current_dir, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(current_dir)

        # Never follow symlink directories. `os.walk(..., followlinks=False)` already
        # avoids descent, but pruning here makes the boundary explicit.
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        if not scope.recursive:
            dirnames[:] = []

        for filename in filenames:
            path = current / filename
            if path.suffix.lower() != ".md" or path.is_symlink():
                continue

            resolved = path.resolve()
            if not _is_within(resolved, root):
                continue

            relative = resolved.relative_to(root).as_posix()
            relative_dir = resolved.parent.relative_to(root).as_posix() or "."
            policy = scope.policy_for(relative_dir)
            if not _included(relative, policy.mode, policy.include, policy.exclude):
                continue

            file_hash = sha256_file(resolved)
            document_id = stable_document_id(scope.namespace, relative)
            discovered.append(
                IndexedMarkdownFile(
                    path=resolved,
                    file_hash=file_hash,
                    document=DocumentRef(
                        namespace=scope.namespace,
                        document_id=document_id,
                        source_uri=resolved.as_uri(),
                        source_version=file_hash,
                        relative_path=relative,
                        metadata={"root": str(root)},
                    ),
                )
            )

    return sorted(discovered, key=lambda item: item.document.relative_path)


def stable_document_id(namespace: str, relative_path: str) -> str:
    raw = f"{namespace}\0{relative_path}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _included(
    relative_path: str,
    mode: ScopeMode,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> bool:
    if matches_any(relative_path, exclude):
        return False
    if mode is ScopeMode.INCLUDE_ONLY:
        return bool(include) and matches_any(relative_path, include)
    return True


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
