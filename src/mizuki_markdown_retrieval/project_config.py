from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .chunking import CHUNK_PROFILES
from .config import FolderOverride, FolderPolicy, ScopeConfig, ScopeMode


class ProjectConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SearchRuntimeConfig:
    database_path: Path
    representation_revision: str
    model_path: Path | None = None
    device: str = "cpu"


@dataclass(frozen=True)
class RuntimeScope:
    name: str
    scope: ScopeConfig
    state_path: Path
    chunk_profile: str = "medium"
    full_reindex_threshold: float = 0.5
    search: SearchRuntimeConfig | None = None


@dataclass(frozen=True)
class ProjectConfig:
    config_path: Path
    scopes: Mapping[str, RuntimeScope]

    def get_scope(self, name: str) -> RuntimeScope:
        try:
            return self.scopes[name]
        except KeyError as exc:
            raise ProjectConfigError(f"unknown scope: {name}") from exc


def load_project_config(path: Path) -> ProjectConfig:
    path = path.expanduser().resolve()
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectConfigError(f"failed to read TOML config: {path}") from exc

    raw_scopes = payload.get("scope", [])
    if not isinstance(raw_scopes, list) or not raw_scopes:
        raise ProjectConfigError("config must contain at least one [[scope]] table")

    base_dir = path.parent
    scopes: dict[str, RuntimeScope] = {}
    for raw in raw_scopes:
        runtime = _parse_scope(raw, base_dir)
        if runtime.name in scopes:
            raise ProjectConfigError(f"duplicate scope name: {runtime.name}")
        scopes[runtime.name] = runtime

    return ProjectConfig(config_path=path, scopes=scopes)


def _parse_scope(raw: object, base_dir: Path) -> RuntimeScope:
    if not isinstance(raw, dict):
        raise ProjectConfigError("each [[scope]] entry must be a table")

    name = _required_text(raw, "name")
    namespace = _required_text(raw, "namespace")
    root = _resolve_path(base_dir, _required_text(raw, "root"))
    recursive = bool(raw.get("recursive", True))
    mode = _parse_mode(raw.get("mode", ScopeMode.INCLUDE_ALL_EXCEPT.value))
    include = _string_tuple(raw.get("include", ()), "include")
    exclude = _string_tuple(raw.get("exclude", ()), "exclude")

    overrides = tuple(_parse_override(item) for item in raw.get("override", []))
    scope = ScopeConfig(
        namespace=namespace,
        root=root,
        recursive=recursive,
        policy=FolderPolicy(mode=mode, include=include, exclude=exclude),
        overrides=overrides,
    )

    state_raw = str(raw.get("state_path", f"local/{name}.index-state.json"))
    state_path = _resolve_path(base_dir, state_raw)
    chunk_profile = str(raw.get("chunk_profile", "medium"))
    if chunk_profile not in CHUNK_PROFILES:
        raise ProjectConfigError(f"unknown chunk_profile for {name}: {chunk_profile}")

    try:
        threshold = float(raw.get("full_reindex_threshold", 0.5))
    except (TypeError, ValueError) as exc:
        raise ProjectConfigError(
            f"full_reindex_threshold for {name} must be numeric"
        ) from exc
    if not 0 <= threshold <= 1:
        raise ProjectConfigError(
            f"full_reindex_threshold for {name} must be between 0 and 1"
        )

    search = _parse_search_runtime(raw.get("search"), base_dir, name)

    return RuntimeScope(
        name=name,
        scope=scope,
        state_path=state_path,
        chunk_profile=chunk_profile,
        full_reindex_threshold=threshold,
        search=search,
    )


def _parse_search_runtime(
    raw: object,
    base_dir: Path,
    scope_name: str,
) -> SearchRuntimeConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProjectConfigError(f"scope.search for {scope_name} must be a table")

    database_path = _resolve_path(base_dir, _required_text(raw, "database_path"))
    revision = _required_text(raw, "representation_revision")
    model_raw = raw.get("model_path")
    if model_raw is None:
        model_path = None
    elif isinstance(model_raw, str) and model_raw.strip():
        model_path = _resolve_path(base_dir, model_raw.strip())
    else:
        raise ProjectConfigError(
            f"model_path for {scope_name} must be non-empty text when provided"
        )
    device = str(raw.get("device", "cpu")).strip()
    if not device:
        raise ProjectConfigError(f"device for {scope_name} must not be blank")
    return SearchRuntimeConfig(
        database_path=database_path,
        representation_revision=revision,
        model_path=model_path,
        device=device,
    )


def _parse_override(raw: object) -> FolderOverride:
    if not isinstance(raw, dict):
        raise ProjectConfigError("[[scope.override]] entries must be tables")
    relative_dir = _required_text(raw, "relative_dir")
    mode = _parse_mode(raw["mode"]) if "mode" in raw else None
    include = _string_tuple(raw["include"], "include") if "include" in raw else None
    exclude = _string_tuple(raw["exclude"], "exclude") if "exclude" in raw else None
    return FolderOverride(
        relative_dir=relative_dir,
        inherit=bool(raw.get("inherit", True)),
        mode=mode,
        include=include,
        exclude=exclude,
    )


def _parse_mode(value: object) -> ScopeMode:
    try:
        return ScopeMode(str(value))
    except ValueError as exc:
        valid = ", ".join(item.value for item in ScopeMode)
        raise ProjectConfigError(f"unknown scope mode {value!r}; expected: {valid}") from exc


def _required_text(raw: Mapping[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"{key} is required and must be non-empty text")
    return value.strip()


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value
    raise ProjectConfigError(f"{field_name} must be a string array")


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
