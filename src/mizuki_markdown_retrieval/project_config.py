from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .chunking import CHUNK_PROFILES
from .config import FolderOverride, FolderPolicy, ScopeConfig, ScopeMode

_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProjectConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SearchRuntimeConfig:
    database_url_env: str
    schema: str
    vector_dimensions: int
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
class ManagementConfig:
    """Machine-local scope-management boundary.

    The public MCP can browse and manage only underneath ``browse_root``. The
    root itself is intentionally absent from MCP write operations and is changed
    only through local configuration/CLI.
    """

    settings_path: Path
    browse_root: Path
    managed_scopes_path: Path
    template_scope: str
    include_hidden: bool = False


@dataclass(frozen=True)
class ProjectConfig:
    config_path: Path
    scopes: Mapping[str, RuntimeScope]
    management: ManagementConfig | None = None
    managed_scope_names: frozenset[str] = frozenset()

    def get_scope(self, name: str) -> RuntimeScope:
        try:
            return self.scopes[name]
        except KeyError as exc:
            raise ProjectConfigError(f"unknown scope: {name}") from exc

    def is_managed_scope(self, name: str) -> bool:
        return name in self.managed_scope_names


def local_settings_path(config_path: Path) -> Path:
    config_path = config_path.expanduser().resolve()
    return config_path.with_name(f"{config_path.stem}.local.toml")


def default_managed_scopes_path(config_path: Path) -> Path:
    config_path = config_path.expanduser().resolve()
    return config_path.with_name(f"{config_path.stem}.managed-scopes.toml")


def load_project_config(path: Path) -> ProjectConfig:
    path = path.expanduser().resolve()
    payload = _read_toml(path)

    raw_scopes = payload.get("scope", [])
    if not isinstance(raw_scopes, list):
        raise ProjectConfigError("config scope must be an array of tables")

    base_dir = path.parent
    scopes: dict[str, RuntimeScope] = {}
    for raw in raw_scopes:
        runtime = _parse_scope(raw, base_dir)
        if runtime.name in scopes:
            raise ProjectConfigError(f"duplicate scope name: {runtime.name}")
        scopes[runtime.name] = runtime

    management = _load_management_config(path, scopes)
    managed_scope_names: set[str] = set()
    if management is not None and management.managed_scopes_path.exists():
        managed_payload = _read_toml(management.managed_scopes_path)
        managed_raw = managed_payload.get("scope", [])
        if not isinstance(managed_raw, list):
            raise ProjectConfigError("managed scope file must contain [[scope]] tables")
        for raw in managed_raw:
            if not isinstance(raw, dict):
                raise ProjectConfigError("each managed [[scope]] entry must be a table")
            template_name = str(raw.get("template", management.template_scope)).strip()
            try:
                template = scopes[template_name]
            except KeyError as exc:
                raise ProjectConfigError(
                    f"managed scope template does not exist: {template_name}"
                ) from exc
            runtime = _parse_scope(raw, management.managed_scopes_path.parent, template=template)
            if runtime.name in scopes:
                raise ProjectConfigError(f"duplicate scope name: {runtime.name}")
            scopes[runtime.name] = runtime
            managed_scope_names.add(runtime.name)

    if not scopes:
        raise ProjectConfigError("config must contain at least one scope")

    if management is not None and management.template_scope not in scopes:
        raise ProjectConfigError(
            f"management template_scope does not exist: {management.template_scope}"
        )

    return ProjectConfig(
        config_path=path,
        scopes=scopes,
        management=management,
        managed_scope_names=frozenset(managed_scope_names),
    )


def _read_toml(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProjectConfigError(f"failed to read TOML config: {path}") from exc


def _load_management_config(
    config_path: Path,
    base_scopes: Mapping[str, RuntimeScope],
) -> ManagementConfig | None:
    settings_path = local_settings_path(config_path)
    if not settings_path.exists():
        return None
    payload = _read_toml(settings_path)
    raw = payload.get("management")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProjectConfigError("[management] must be a table")

    browse_root = _resolve_path(settings_path.parent, _required_text(raw, "browse_root"))
    template_scope = _required_text(raw, "template_scope")
    if base_scopes and template_scope not in base_scopes:
        raise ProjectConfigError(f"management template_scope does not exist: {template_scope}")
    managed_raw = str(raw.get("managed_scopes_path", "")).strip()
    managed_scopes_path = (
        _resolve_path(settings_path.parent, managed_raw)
        if managed_raw
        else default_managed_scopes_path(config_path)
    )
    return ManagementConfig(
        settings_path=settings_path,
        browse_root=browse_root,
        managed_scopes_path=managed_scopes_path,
        template_scope=template_scope,
        include_hidden=bool(raw.get("include_hidden", False)),
    )


def _parse_scope(
    raw: object,
    base_dir: Path,
    *,
    template: RuntimeScope | None = None,
) -> RuntimeScope:
    if not isinstance(raw, dict):
        raise ProjectConfigError("each [[scope]] entry must be a table")

    name = _required_text(raw, "name")
    namespace_value = raw.get("namespace", name)
    if not isinstance(namespace_value, str) or not namespace_value.strip():
        raise ProjectConfigError("namespace must be non-empty text")
    namespace = namespace_value.strip()
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

    if "state_path" in raw:
        state_path = _resolve_path(base_dir, str(raw["state_path"]))
    elif template is not None:
        state_path = template.state_path.parent / f"{name}.index-state.json"
    else:
        state_path = _resolve_path(base_dir, f"local/{name}.index-state.json")

    chunk_profile = str(
        raw.get("chunk_profile", template.chunk_profile if template is not None else "medium")
    )
    if chunk_profile not in CHUNK_PROFILES:
        raise ProjectConfigError(f"unknown chunk_profile for {name}: {chunk_profile}")

    threshold_default = template.full_reindex_threshold if template is not None else 0.5
    try:
        threshold = float(raw.get("full_reindex_threshold", threshold_default))
    except (TypeError, ValueError) as exc:
        raise ProjectConfigError(
            f"full_reindex_threshold for {name} must be numeric"
        ) from exc
    if not 0 <= threshold <= 1:
        raise ProjectConfigError(
            f"full_reindex_threshold for {name} must be between 0 and 1"
        )

    if "search" in raw:
        search = _parse_search_runtime(raw.get("search"), base_dir, name)
    elif template is not None:
        search = template.search
    else:
        search = None

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

    database_url_env = _required_text(raw, "database_url_env")
    schema = _required_text(raw, "schema")
    if not _SCHEMA_RE.fullmatch(schema):
        raise ProjectConfigError(
            f"schema for {scope_name} must be a simple PostgreSQL identifier"
        )
    try:
        vector_dimensions = int(raw.get("vector_dimensions"))
    except (TypeError, ValueError) as exc:
        raise ProjectConfigError(
            f"vector_dimensions for {scope_name} must be an integer"
        ) from exc
    if not 1 <= vector_dimensions <= 2000:
        raise ProjectConfigError(
            f"vector_dimensions for {scope_name} must be between 1 and 2000"
        )
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
        database_url_env=database_url_env,
        schema=schema,
        vector_dimensions=vector_dimensions,
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
