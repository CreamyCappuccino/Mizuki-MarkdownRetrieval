from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Iterable


class ScopeMode(str, Enum):
    INCLUDE_ALL_EXCEPT = "include_all_except"
    INCLUDE_ONLY = "include_only"


@dataclass(frozen=True)
class FolderPolicy:
    mode: ScopeMode = ScopeMode.INCLUDE_ALL_EXCEPT
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class FolderOverride:
    """Optional child-folder override.

    `inherit=True` applies the override to descendants too. With `inherit=False`
    it applies only to the named folder.
    """

    relative_dir: str
    inherit: bool = True
    mode: ScopeMode | None = None
    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ScopeConfig:
    namespace: str
    root: Path
    recursive: bool = True
    policy: FolderPolicy = FolderPolicy()
    overrides: tuple[FolderOverride, ...] = ()

    def policy_for(self, relative_dir: str | PurePosixPath) -> FolderPolicy:
        directory = PurePosixPath(relative_dir or ".")
        current = self.policy
        matches: list[tuple[int, FolderOverride]] = []
        for override in self.overrides:
            target = PurePosixPath(override.relative_dir or ".")
            applies = directory == target or (
                override.inherit and _is_same_or_descendant(directory, target)
            )
            if applies:
                matches.append((len(target.parts), override))

        for _, override in sorted(matches, key=lambda item: item[0]):
            current = replace(
                current,
                mode=override.mode if override.mode is not None else current.mode,
                include=override.include if override.include is not None else current.include,
                exclude=override.exclude if override.exclude is not None else current.exclude,
            )
        return current


def matches_any(relative_path: str, patterns: Iterable[str]) -> bool:
    path = PurePosixPath(relative_path)
    for pattern in patterns:
        normalized = pattern.strip().replace("\\", "/")
        if not normalized:
            continue
        if path.match(normalized) or path.name == normalized:
            return True
    return False


def _is_same_or_descendant(path: PurePosixPath, parent: PurePosixPath) -> bool:
    if str(parent) in ("", "."):
        return True
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
